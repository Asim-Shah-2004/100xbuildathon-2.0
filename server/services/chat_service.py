from crewai import Agent, Task, Crew, Process
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
import os
import psycopg2
import pandas as pd
import requests
import ast
from PyPDF2 import PdfReader
import tempfile
import json
from urllib.parse import urlparse, parse_qs
import re
import gdown
import litellm
import io
import sys
import uuid
from datetime import datetime
from composio_openai import ComposioToolSet
from composio import App, Action
import fitz  # PyMuPDF for PDF highlighting

load_dotenv()

TEMP_DIR = os.path.join(os.path.dirname(__file__), "..", "temp")
HIGHLIGHTED_DIR = os.path.join(os.path.dirname(__file__), "..", "highlighted_resumes")

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)
if not os.path.exists(HIGHLIGHTED_DIR):
    os.makedirs(HIGHLIGHTED_DIR)

toolset = ComposioToolSet()


class LiteLLMAgent(Agent):
    def __init__(self, role, goal, backstory, **kwargs):
        super().__init__(
            role=role, goal=goal, backstory=backstory, allow_delegation=False, **kwargs
        )

    def execute_task(self, task, context=None, tools=None):
        try:
            print(f"Executing task: {task.description}")
            response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": task.description}],
                api_key=os.getenv("GOOGLE_API_KEY"),
            )
            print(f"LiteLLM Response: {response}")

            output_content = response.choices[0].message.content
            print(f"Output content: {output_content}")
            return output_content
        except Exception as e:
            print(f"Error in LiteLLMAgent execution: {e}")
            return f"Error: {e}"


class ChatService:
    def __init__(self):
        self.data_processor = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            temperature=0,
        )

        self.connection_string = os.getenv("CONNECTION_URL")
        self._init_db()

    def _init_db(self):
        try:
            db = SQLDatabase.from_uri(self.connection_string)
            print(db)
            # Use invoke instead of run (deprecated method)
            db.run_no_throw(
                """
                CREATE TABLE IF NOT EXISTS rejected_candidates (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255),
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) 
            """
            )
        except Exception as e:
            raise Exception(f"Error initializing database: {str(e)}")

    def _get_db_connection(self):
        try:
            parsed = urlparse(self.connection_string)
            db_config = {
                "host": parsed.hostname,
                "port": parsed.port or 5432,
                "user": parsed.username,
                "password": parsed.password,
                "database": parsed.path.lstrip("/"),
            }
            return psycopg2.connect(**db_config)
        except Exception as e:
            raise Exception(f"Error creating database connection: {str(e)}")

    def rephrase_with_chat_context(self, query, user_id, table_name, connection):
        cursor = connection.cursor()

        # Fetch last 10 messages for context
        cursor.execute(
            """
            SELECT question, response FROM private.threads
            WHERE user_id = %s AND table_id = %s
            ORDER BY timestamp DESC
            LIMIT 10
        """,
            (user_id, table_name),
        )

        history = cursor.fetchall()
        cursor.close()

        if not history:
            return query  # No context, return as-is

        # Build chat history string
        chat_context = "\n".join([f"User: {q}\nBot: {r}" for q, r in reversed(history)])

        prompt = f"""
        You are an AI assistant helping with SQL-related questions based on previous conversation history.

        Conversation so far:
        {chat_context}

        New user question: "{query}"

        Determine whether this new question is a follow-up. 
        If yes, rephrase it into a fully self-contained question that includes the necessary context from earlier (ensure that you rephrase the question such that it can become a proper self contained text to sql query).
        If it is not related, simply return the original question as-is.

        **IMPORTANT GUIDELINE - 
        1. ONly return the rephrased/original question in the string format nothing else.

        Rephrased or original question:
        """

        # Call LLM to rephrase
        response = litellm.completion(
            model="gemini/gemini-2.0-flash",
            messages=[{"role": "user", "content": prompt}],
            api_key=os.getenv("GOOGLE_API_KEY"),
        )

        rephrased_question = response.choices[0].message.content.strip()

        print("till here 2 - ", rephrased_question)

        # if isinstance(rephrased_question, str):
        #     return response.get("output", query)
        return rephrased_question

    def detect_intent(self, question: str) -> str:
        intent_prompt = f"""
            You are an intent classifier for an HR assistant.

            Classify the intent of the following user question into one of:
            - "sql": if the question relates to querying a candidate database.
            - "gmail": if it involves sending, replying to, or checking emails.
            - "calendar": if it involves scheduling or managing meetings on a calendar.
            - "unknown": if the intent is unclear or unsupported.

            User Question: "{question}"

            Respond with only one word: "sql", "gmail", "calendar", or "unknown".
            """
        response = litellm.completion(
            model="gemini/gemini-2.0-flash",
            messages=[{"role": "user", "content": intent_prompt}],
            api_key=os.getenv("GOOGLE_API_KEY"),
        )

        return response.choices[0].message.content.strip().lower()

    def process_query(self, table_name, query, user_id):
        try:
            # Create SQL agent with proper configuration
            db = SQLDatabase.from_uri(
                self.connection_string, include_tables=[table_name]
            )

            # Create SQL toolkit and agent
            toolkit = SQLDatabaseToolkit(db=db, llm=self.data_processor)
            agent = create_sql_agent(
                llm=self.data_processor,
                toolkit=toolkit,
                verbose=True,
                agent_type="openai-tools",
                handle_parsing_errors=True,
            )

            # First, get the table schema to provide context
            connection = self._get_db_connection()
            cursor = connection.cursor()

            # create a rephraser layer which will access the past 10 chat history in the thread and then create a contextually aware chat interface
            # Add this before enhanced_query is constructed
            rephrased_query = self.rephrase_with_chat_context(
                query, user_id, table_name, connection
            )

            print(
                "------------------------STAGE 0 QUERY REPHRASER------------------------"
            )
            print(rephrased_query)
            print(
                "------------------------STAGE 0 QUERY REPHRASER------------------------"
            )

            # now checking the intent of the query to route it appropritely to the user
            intent = self.detect_intent(rephrased_query)
            print(
                "------------------------STAGE 1 INTENT DETECTOR------------------------"
            )
            print(intent)
            print(
                "------------------------STAGE 1 INTENT DETECTOR------------------------"
            )

            if intent == "gmail":
                return self.send_mail_to_candidates(rephrased_query)
            elif intent == "calendar":
                return self.create_calendar_event()
            elif intent == "sql":
                try:
                    cursor.execute(
                        f"""
                        SELECT column_name, data_type 
                        FROM information_schema.columns 
                        WHERE table_name = '{table_name}' 
                        AND table_schema = 'public'
                        ORDER BY ordinal_position
                    """
                    )
                    schema = cursor.fetchall()

                    if not schema:
                        return f"Table '{table_name}' not found or has no accessible columns."

                    # Get sample data to understand the table better
                    cursor.execute(f'SELECT * FROM "{table_name}" LIMIT 3')
                    sample_data = cursor.fetchall()

                    # Build enhanced prompt with context
                    schema_info = "\n".join(
                        [f"- {col[0]} ({col[1]})" for col in schema]
                    )

                    enhanced_query = f"""
                    You are a helpful AI assistant designed to support HR professionals by answering questions about candidate data from the database.

                    Table '{table_name}' has the following schema:
                    {schema_info}

                    User question: "{rephrased_query}"

                    Your job is to:
                    1. **Write and execute a SQL query** to accurately answer the user's question using the schema.
                    2. Present the **answer in a professional, clear, and human-readable format**, ideally structured in:
                    - **Summary headers**
                    - **Bullet points** or **tables** (if the data has multiple rows or categories)
                    - Add brief **interpretation/explanation** of the data in simple terms.
                    3. If the question involves candidate availability, communication status, or next steps, **answer conversationally** like an assistant helping an HR person.
                    4. If the question is about contacting or emailing the candidate, respond with:
                    👉 "Yes, sending email to the candidate."

                    Please format the final answer like this:
                    ---
                    **🔍 Answer Summary**
                    A one-line headline of the answer

                    **📊 Data Overview**
                    Table or bullet points showing the SQL result

                    **🧠 Interpretation**
                    Plain-English explanation of what this data means

                    ---
                    Only include sections that make sense for the result. Be brief but informative.
                    """

                    # Use invoke instead of run
                    result = agent.invoke({"input": enhanced_query})

                    # print("here was the llm response - ", result["output"])

                    # Extract the output from the result
                    if isinstance(result, dict):
                        final_resp = result.get("output", str(result))
                    else:
                        final_resp = str(result)

                    followup_prompt = f"""
                        You are an AI assistant helping HR professionals analyze candidate data.

                        Given the following user question and the AI-generated answer (based on SQL results), generate a list of 3 most relevant and logical follow-up questions.

                        Guidelines:
                        - The follow-up questions must be **resolvable using SQL queries** on the same table.
                        - They should be **related** to the user's original question and **extend the conversation meaningfully**.
                        - Avoid vague or generic questions.
                        - The questions should help the HR make informed decisions or take actions.
                        - Do NOT repeat the original question or restate its answer.

                        Return ONLY a JSON list of 3 strings in the following format - 
                        

                        Original Question:
                        {rephrased_query}

                        LLM Answer:
                        {final_resp}

                        Your output:
                    """

                    followup_response = litellm.completion(
                        model="gemini/gemini-2.0-flash",
                        messages=[{"role": "user", "content": followup_prompt}],
                        api_key=os.getenv("GOOGLE_API_KEY"),
                    )

                    followups = followup_response.choices[0].message.content.strip()
                    followups = (
                        followups.replace("```json", "").replace("```", "").strip()
                    )
                    return {
                        "response": final_resp,
                        "followups": ast.literal_eval(followups),
                    }

                finally:
                    # first checking if a thread id already exists
                    cursor.execute(
                        f"""
                        SELECT thread_id
                        FROM private.threads 
                        WHERE table_id = '{table_name}' 
                        AND user_id = '{user_id}'
                    """
                    )
                    get_thread_id = cursor.fetchone()
                    thread_id = get_thread_id[0] if get_thread_id else str(uuid.uuid4())
                    # once we get the response from the llm for the natural language question asked by the user we need to store the conversation for chat history retreival
                    # Get current timestamp
                    current_timestamp = datetime.now()
                    insert_columns = "user_id, table_id, question, response, thread_id, timestamp, message_id"
                    placeholders = ", ".join(["%s"] * 7)
                    insert_sql = f"INSERT INTO private.threads ({insert_columns}) VALUES ({placeholders})"

                    values = [
                        user_id,
                        table_name,
                        rephrased_query,
                        final_resp,
                        thread_id,
                        current_timestamp,
                        str(uuid.uuid4()),
                    ]

                    print(values)

                    print(f"Debug: Inserting conversation data...")
                    cursor.execute(insert_sql, values)
                    connection.commit()
                    cursor.close()
                    connection.close()
            else:
                return "I'm not sure if I can answer this! Can you retry!"
        except Exception as e:
            print(f"Error in process_query: {str(e)}")
            # Fallback to direct SQL execution if agent fails
            try:
                return self._execute_direct_query(table_name, query)
            except Exception as fallback_error:
                return f"Error processing query: {str(e)}\nFallback error: {str(fallback_error)}"

    def _execute_direct_query(self, table_name, query):
        """Fallback method to execute queries directly"""
        try:
            connection = self._get_db_connection()
            cursor = connection.cursor()

            # Get table schema
            cursor.execute(
                f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = '{table_name}' 
                AND table_schema = 'public'
                ORDER BY ordinal_position
            """
            )
            schema = cursor.fetchall()

            if not schema:
                return f"Table '{table_name}' not found."

            schema_info = "\n".join([f"- {col[0]} ({col[1]})" for col in schema])

            # Use LLM to generate SQL query
            prompt = f"""
            You are a SQL expert. Generate a SQL query for the following request.
            
            Table: {table_name}
            Schema:
            {schema_info}
            
            User Query: {query}
            
            Return ONLY the SQL query, no explanations or formatting.
            """

            response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": prompt}],
                api_key=os.getenv("GOOGLE_API_KEY"),
            )

            sql_query = response.choices[0].message.content.strip()

            # Clean up the SQL query
            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()

            # Execute the query
            cursor.execute(sql_query)
            results = cursor.fetchall()

            # Get column names for results
            column_names = [desc[0] for desc in cursor.description]

            # Format results
            if not results:
                return "No results found for your query."

            # Create a formatted response
            formatted_results = []
            for row in results:
                row_dict = dict(zip(column_names, row))
                formatted_results.append(row_dict)

            # Generate explanation using LLM
            explanation_prompt = f"""
            Explain these SQL query results in a user-friendly way:
            
            Query: {query}
            SQL executed: {sql_query}
            Results: {formatted_results[:5]}  # Show first 5 results
            Total rows: {len(results)}
            
            Provide a clear, concise explanation of what the results show.
            """

            explanation_response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": explanation_prompt}],
                api_key=os.getenv("GOOGLE_API_KEY"),
            )

            explanation = explanation_response.choices[0].message.content

            cursor.close()
            connection.close()

            return f"{explanation}\n\nSQL Query executed: {sql_query}\nTotal results: {len(results)}"

        except Exception as e:
            if "cursor" in locals():
                cursor.close()
            if "connection" in locals():
                connection.close()
            raise Exception(f"Error in direct query execution: {str(e)}")

    def process_new_chat(self, df, jd_text, table_name):
        try:

            print("Step 1: Analyzing job description to determine required columns...")
            columns_response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[
                    {
                        "role": "user",
                        "content": f'Analyze this job description and determine what columns should be in a candidates database table. Return ONLY a JSON array of column names that would be useful for storing candidate information relevant to this job. Include standard fields like name, email, phone, skills, experience, education, etc. Example format: ["name", "email", "phone", "skills", "experience", "education", "linkedin"].\n\nJob Description:\n{jd_text}',
                    }
                ],
                api_key=os.getenv("GOOGLE_API_KEY"),
            )

            columns_content = columns_response.choices[0].message.content.strip()
            print(f"Debug: Raw columns response: {columns_content}")

            if columns_content.startswith("```json"):
                columns_content = columns_content[len("```json") :].lstrip()
            if columns_content.endswith("```"):
                columns_content = columns_content[: -len("```")].rstrip()

            try:
                columns = json.loads(columns_content)
                if not isinstance(columns, list) or not columns:
                    raise ValueError("Expected non-empty list")
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Failed to parse columns JSON, using default: {e}")

                columns = [
                    "name",
                    "email",
                    "phone",
                    "skills",
                    "experience",
                    "education",
                    "linkedin",
                ]

            print(f"Debug: Extracted columns: {columns}")

            if "score" not in [col.lower() for col in columns]:
                columns.append("score")

            print(f"Step 2: Creating table {table_name} with columns: {columns}")
            connection = self._get_db_connection()

            # Add highlighted_pdf_url column if not present
            if "highlighted_pdf_url" not in [col.lower() for col in columns]:
                columns.append("highlighted_pdf_url")

            try:
                cursor = connection.cursor()

                cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')

                create_table_columns = ", ".join([f'"{col}" TEXT' for col in columns])
                create_table_sql = f"""
                    CREATE TABLE "{table_name}" (
                        id SERIAL PRIMARY KEY,
                        {create_table_columns},
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """
                print(f"Debug: CREATE TABLE SQL: {create_table_sql}")
                cursor.execute(create_table_sql)
                connection.commit()
                print(f"Table {table_name} created successfully")

                print("Step 3: Processing candidates...")
                processed_count = 0

                for index, row in df.iterrows():
                    try:
                        print(f"Processing candidate {index + 1}/{len(df)}")

                        resume_text = self._download_and_extract_resume(row["pdf_url"])
                        print(
                            f"Resume text extracted, length: {len(resume_text)} characters"
                        )

                        print("Extracting candidate information...")
                        candidate_info = self._extract_candidate_info_for_jd(
                            resume_text, jd_text, columns
                        )
                        print(
                            f"Candidate info extracted: {list(candidate_info.keys())}"
                        )

                        print("Calculating match score...")
                        score = self._calculate_score(candidate_info, jd_text)
                        candidate_info["score"] = str(score)
                        print(f"Match score: {score}")

                        # Download the PDF for highlighting
                        temp_pdf_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}_resume.pdf")
                        response = requests.get(row["pdf_url"])
                        with open(temp_pdf_path, "wb") as temp_pdf:
                            temp_pdf.write(response.content)

                        # Highlight relevant fields in the PDF
                        highlighted_pdf_filename = f"{uuid.uuid4()}_highlighted.pdf"
                        highlighted_pdf_path = os.path.join(HIGHLIGHTED_DIR, highlighted_pdf_filename)
                        self.highlight_pdf_fields(temp_pdf_path, candidate_info, highlighted_pdf_path)
                        candidate_info["highlighted_pdf_url"] = highlighted_pdf_filename

                        insert_columns = ", ".join([f'"{col}"' for col in columns])
                        placeholders = ", ".join(["%s"] * len(columns))
                        insert_sql = f'INSERT INTO "{table_name}" ({insert_columns}) VALUES ({placeholders})'

                        values = []
                        for col in columns:
                            value = candidate_info.get(col, "")
                            if value is None:
                                values.append("")
                            else:
                                values.append(str(value))

                        print(f"Debug: Inserting candidate data...")
                        cursor.execute(insert_sql, values)
                        connection.commit()
                        processed_count += 1
                        print(f"Candidate {index + 1} processed successfully")

                        # Clean up temp files
                        if os.path.exists(temp_pdf_path):
                            os.remove(temp_pdf_path)

                    except Exception as candidate_error:
                        print(
                            f"Error processing candidate {index + 1}: {candidate_error}"
                        )
                        continue

                print(
                    f"Processing completed. {processed_count} candidates processed successfully."
                )

            except Exception as e:
                connection.rollback()
                raise Exception(f"Database operation failed: {e}")
            finally:
                cursor.close()
                connection.close()

            return {
                "message": f"Processing completed successfully. {processed_count} candidates processed."
            }

        except Exception as e:
            raise Exception(f"Error processing new chat: {str(e)}")

    def _is_google_drive_url(self, url):
        return "drive.google.com" in url

    def _get_google_drive_file_id(self, url):
        if "id=" in url:
            return parse_qs(urlparse(url).query)["id"][0]
        elif "/d/" in url:
            return url.split("/d/")[1].split("/")[0]
        return None

    def _download_and_extract_resume(self, pdf_url):
        try:

            temp_file_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}.pdf")

            if self._is_google_drive_url(pdf_url):
                file_id = self._get_google_drive_file_id(pdf_url)
                if not file_id:
                    raise Exception("Invalid Google Drive URL")

                gdown.download(
                    f"https://drive.google.com/uc?id={file_id}",
                    temp_file_path,
                    quiet=False,
                )

                if (
                    not os.path.exists(temp_file_path)
                    or os.path.getsize(temp_file_path) == 0
                ):
                    raise Exception("Failed to download file from Google Drive")
            else:
                response = requests.get(pdf_url)
                if response.status_code != 200:
                    raise Exception(f"Failed to download PDF: {response.status_code}")

                with open(temp_file_path, "wb") as temp_file:
                    temp_file.write(response.content)

            pdf_reader = PdfReader(temp_file_path)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text()

            os.unlink(temp_file_path)
            return text

        except Exception as e:

            if "temp_file_path" in locals() and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception as cleanup_error:
                    print(
                        f"Error cleaning up temporary file {temp_file_path}: {cleanup_error}"
                    )
            raise Exception(f"Error downloading or processing PDF: {str(e)}")

    def _extract_candidate_info(self, resume_text):
        try:
            response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[
                    {
                        "role": "user",
                        "content": f"Extract candidate information from this resume:\n{resume_text}\nReturn ONLY a JSON object with the extracted information. Structure the JSON with relevant keys like 'name', 'email', 'phone', 'linkedin', 'skills', 'experience', 'education'. Ensure the output is ONLY the JSON object, for example: {{ \"name\": \"John Doe\", \"email\": \"john.doe@example.com\" }}. Do NOT include any other text or formatting before or after the JSON.",
                    }
                ],
                api_key=os.getenv("GOOGLE_API_KEY"),
            )

            llm_output_content = response.choices[0].message.content.strip()
            print(f"Debug: Raw LLM output for candidate info: {llm_output_content}")

            if llm_output_content.startswith("```json"):
                llm_output_content = llm_output_content[len("```json") :].lstrip()
            if llm_output_content.endswith("```"):
                llm_output_content = llm_output_content[: -len("```")].rstrip()

            return json.loads(llm_output_content)
        except json.JSONDecodeError as e:

            raise Exception(
                f"Error decoding JSON from LLM output for candidate info. Raw output: {llm_output_content}. Error: {e}"
            )
        except Exception as e:
            raise Exception(f"Error extracting candidate info: {str(e)}")

    def _extract_candidate_info_for_jd(self, resume_text, jd_text, required_columns):

        try:
            columns_str = ", ".join(required_columns[:-1])

            prompt = f"""
            Extract candidate information from this resume based on the job description requirements.
            
            Job Description:
            {jd_text}
            
            Resume Text:
            {resume_text}
            
            Extract information for these specific fields: {columns_str}
            
            Return ONLY a JSON object with the extracted information. Map the resume content to the required fields.
            For skills, include relevant technical skills, programming languages, frameworks, tools mentioned.
            For experience, summarize relevant work history and projects.
            For education, include degrees, certifications, relevant coursework.
            
            Example format: {{"name": "John Doe", "email": "john@email.com", "skills": "Python, Machine Learning, AWS", "experience": "5 years in AI development"}}
            
            Return ONLY the JSON object, no other text.
            """

            response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": prompt}],
                api_key=os.getenv("GOOGLE_API_KEY"),
            )

            llm_output_content = response.choices[0].message.content.strip()
            print(
                f"Debug: Raw LLM output for JD-specific candidate info: {llm_output_content[:200]}..."
            )

            if llm_output_content.startswith("```json"):
                llm_output_content = llm_output_content[len("```json") :].lstrip()
            if llm_output_content.endswith("```"):
                llm_output_content = llm_output_content[: -len("```")].rstrip()

            candidate_info = json.loads(llm_output_content)

            for col in required_columns:
                if col != "score" and col not in candidate_info:
                    candidate_info[col] = ""

            return candidate_info

        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            print(f"Raw output: {llm_output_content}")

            default_info = {}
            for col in required_columns:
                if col != "score":
                    default_info[col] = ""
            return default_info
        except Exception as e:
            raise Exception(f"Error extracting JD-specific candidate info: {str(e)}")

    def _calculate_score(self, candidate_info, jd_text):
        try:
            response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[
                    {
                        "role": "user",
                        "content": f"Calculate a match score (0-100) between this candidate and job description. Return ONLY the score number as a float.\nCandidate: {json.dumps(candidate_info)}\nJob Description: {jd_text}",
                    }
                ],
                api_key=os.getenv("GOOGLE_API_KEY"),
            )
            return float(response.choices[0].message.content.strip())
        except Exception as e:
            raise Exception(f"Error calculating score: {str(e)}")

    def _add_to_rejected(self, name, reason):
        connection = self._get_db_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO rejected_candidates (name, reason) VALUES (%s, %s)",
                (name, reason),
            )
            connection.commit()
        except Exception as e:
            connection.rollback()
            raise Exception(f"Error adding to rejected candidates: {str(e)}")
        finally:
            cursor.close()
            connection.close()

    def get_all_tables(self):
        try:
            connection = self._get_db_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
            """
            )
            tables_result = cursor.fetchall()

            tables = [row[0] for row in tables_result]

            cursor.close()
            connection.close()

            return tables

        except Exception as e:
            raise Exception(f"Error getting tables: {str(e)}")

    def get_all_chats_in_thread(self, table_name, user_id):
        try:
            connection = self._get_db_connection()
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT question, response 
                FROM private.threads 
                WHERE table_id = %s
                AND user_id = %s
                ORDER BY timestamp ASC
            """,
                (table_name, user_id),
            )
            chat_results = cursor.fetchall()

            cursor.close()
            connection.close()

            return chat_results

        except Exception as e:
            raise Exception(f"Error getting tables: {str(e)}")

    def get_table_insights(self, table_name):
        try:
            connection = self._get_db_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = %s
                ORDER BY ordinal_position
            """,
                (table_name,),
            )
            columns_result = cursor.fetchall()
            columns = [row[0] for row in columns_result]

            cursor.execute(f'SELECT * FROM "{table_name}"')
            data_result = cursor.fetchall()

            table_data = []
            for row in data_result:
                row_dict = {}
                for i, col in enumerate(columns):
                    if i < len(row):
                        value = row[i]
                        row_dict[col] = str(value) if value is not None else None
                    else:
                        row_dict[col] = None
                table_data.append(row_dict)

            cursor.close()
            connection.close()

            return {"columns": columns, "data": table_data}

        except Exception as e:
            raise Exception(f"Error getting table insights: {str(e)}")

    def get_candidate_details(self, candidate_id):
        try:
            connection = self._get_db_connection()
            cursor = connection.cursor()

            # Get all tables
            cursor.execute(
                """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
            """
            )
            tables = [row[0] for row in cursor.fetchall()]

            # Search for candidate in each table
            for table in tables:
                cursor.execute(
                    f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_schema = 'public' 
                    AND table_name = %s
                    ORDER BY ordinal_position
                """,
                    (table,),
                )
                columns = [row[0] for row in cursor.fetchall()]

                # Check if table has id column
                if "id" in columns:
                    cursor.execute(
                        f'SELECT * FROM "{table}" WHERE id = %s', (candidate_id,)
                    )
                    result = cursor.fetchone()

                    if result:
                        # Convert result to dictionary
                        candidate_data = {}
                        for i, col in enumerate(columns):
                            value = result[i]
                            candidate_data[col] = (
                                str(value) if value is not None else None
                            )

                        cursor.close()
                        connection.close()
                        return candidate_data

            cursor.close()
            connection.close()
            return None

        except Exception as e:
            if "cursor" in locals():
                cursor.close()
            if "connection" in locals():
                connection.close()
            raise Exception(f"Error getting candidate details: {str(e)}")

    def get_candidate_details_by_name(self, name):
        try:
            connection = self._get_db_connection()
            cursor = connection.cursor()

            # Get all tables
            cursor.execute(
                """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
            """
            )
            tables = [row[0] for row in cursor.fetchall()]

            # Search for candidate in each table
            for table in tables:
                cursor.execute(
                    f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_schema = 'public' 
                    AND table_name = %s
                    ORDER BY ordinal_position
                """,
                    (table,),
                )
                columns = [row[0] for row in cursor.fetchall()]

                # Check if table has name column
                if "name" in columns:
                    cursor.execute(f'SELECT * FROM "{table}" WHERE name = %s', (name,))
                    result = cursor.fetchone()

                    if result:
                        # Convert result to dictionary
                        candidate_data = {}
                        for i, col in enumerate(columns):
                            value = result[i]
                            candidate_data[col] = (
                                str(value) if value is not None else None
                            )

                        cursor.close()
                        connection.close()
                        return candidate_data

            cursor.close()
            connection.close()
            return None

        except Exception as e:
            if "cursor" in locals():
                cursor.close()
            if "connection" in locals():
                connection.close()
            raise Exception(f"Error getting candidate details: {str(e)}")

    def send_mail_to_candidates(self, query):
        # tools = toolset.get_tools(actions=[Action.GMAIL_SEND_EMAIL])
        tools = toolset.execute_action(
            action=Action.GMAIL_SEND_EMAIL,
            params={
                "body": "Hi mansi here",
                "recipient_email": "mansi.dwivedi@spit.ac.in",
            },
        )
        print("Action completed")
        return tools
        # task = query

        # messages = [
        #     {
        #         "role": "system",
        #         "content": "You are a helpful assistant that can use tools.",
        #     },
        #     {"role": "user", "content": task},
        # ]

        # agent = litellm.create_assistants(
        #     custom_llm_provider="openai",
        #     model="gemini/gemini-2.0-flash",
        #     api_key=os.getenv("GOOGLE_API_KEY"),
        #     tools=tools,
        #     instructions="You are a helpful assistant that can use tools.",
        # )
        # new_thread = litellm.create_thread(
        #     custom_llm_provider="openai",
        #     messages=[{"role": "user", "content": "Hey, could you send an email"}],  # type: ignore
        # )
        # assistant_id = agent.data[0].id
        # response = litellm.run_thread(
        #     custom_llm_provider="openai",
        #     thread_id=new_thread.id,
        #     assistant_id=assistant_id,
        # )

        # print(response)

        # return response

        # response = litellm.completion(
        #     model="gemini/gemini-2.0-flash",
        #     messages=messages,
        #     api_key=os.getenv("GOOGLE_API_KEY"),
        #     tools=tools,  # The tools we prepared earlier
        #     tool_choice="auto",
        # )
        # print(f"LiteLLM Response: {response}")

        # output_content = response.choices[0].message.content
        # # response = client.chat.completions.create(
        # #     model="gpt-4o-mini",  # Or another capable model
        # #     messages=messages,
        # #     tools=tools,  # The tools we prepared earlier
        # #     tool_choice="auto",  # Let the LLM decide whether to use a tool
        # # )
        # result = toolset.handle_tool_calls(response)
        # print(result)
        # return result

    def highlight_pdf_fields(self, pdf_path, extracted_fields, output_path=None):
        """
        Highlights the values of extracted_fields in the PDF at pdf_path.
        Each field gets a different color. Returns the path to the highlighted PDF.
        - Uses case-insensitive search.
        - Skips empty or very short values.
        """
        import random
        color_palette = [
            (1, 1, 0),    # Yellow
            (0, 1, 1),    # Cyan
            (1, 0, 1),    # Magenta
            (1, 0.5, 0),  # Orange
            (0.5, 1, 0),  # Light Green
            (0.5, 0.5, 1),# Light Blue
            (1, 0.8, 0.2) # Gold
        ]
        field_colors = {}
        for i, key in enumerate(extracted_fields.keys()):
            field_colors[key] = color_palette[i % len(color_palette)]

        doc = fitz.open(pdf_path)
        for field, value in extracted_fields.items():
            if not value or not isinstance(value, str) or len(value.strip()) < 3:
                continue
            color = field_colors[field]
            for page in doc:
                # Case-insensitive search for all occurrences
                text_instances = page.search_for(value, quads=True, flags=fitz.TEXT_DEHYPHENATE | fitz.TEXT_IGNORECASE)
                for inst in text_instances:
                    highlight = page.add_highlight_annot(inst.rects)
                    highlight.set_colors(stroke=color)
                    highlight.update()
        if not output_path:
            output_path = pdf_path.replace('.pdf', '_highlighted.pdf')
        doc.save(output_path, garbage=4, deflate=True)
        doc.close()
        return output_path
