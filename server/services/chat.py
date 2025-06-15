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
from pdfrw import PdfReader as PdfrwReader
from pdfrw.buildxobj import pagexobj
from pdfrw.toreportlab import makerl
from reportlab.pdfgen import canvas
from reportlab.lib.colors import yellow, green, blue, red
import base64

load_dotenv()

TEMP_DIR = os.path.join(os.path.dirname(__file__), '..', 'temp')
HIGHLIGHTED_DIR = os.path.join(os.path.dirname(__file__), '..', 'highlighted_resumes')

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)
if not os.path.exists(HIGHLIGHTED_DIR):
    os.makedirs(HIGHLIGHTED_DIR)

class LiteLLMAgent(Agent):
    def __init__(self, role, goal, backstory, **kwargs):
        super().__init__(role=role, goal=goal, backstory=backstory, allow_delegation=False, **kwargs)

    def execute_task(self, task, context=None, tools=None):
        try:
            print(f"Executing task: {task.description}")
            response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": task.description}],
                api_key=os.getenv('GOOGLE_API_KEY')
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
            google_api_key=os.getenv('GOOGLE_API_KEY'),
            temperature=0
        )
        
        self.connection_string = os.getenv('CONNECTION_URL')
        self._init_db()

    def _init_db(self):
        try:
            db = SQLDatabase.from_uri(self.connection_string)
            db.run("""
                CREATE TABLE IF NOT EXISTS rejected_candidates (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255),
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) 
            """)
        except Exception as e:
            raise Exception(f"Error initializing database: {str(e)}")

    def _get_db_connection(self):
        try:
            parsed = urlparse(self.connection_string)
            db_config = {
                'host': parsed.hostname,
                'port': parsed.port or 5432,
                'user': parsed.username,
                'password': parsed.password,
                'database': parsed.path.lstrip('/'),
            }
            return psycopg2.connect(**db_config)
        except Exception as e:
            raise Exception(f"Error creating database connection: {str(e)}")

    def process_query(self, table_name, query):
        try:
            db = SQLDatabase.from_uri(
                self.connection_string,
                include_tables=[table_name]
            )
            
            toolkit = SQLDatabaseToolkit(db=db, llm=self.data_processor)
            agent_executor = create_sql_agent(
                llm=self.data_processor,
                toolkit=toolkit,
                verbose=True,
                agent_type="zero-shot-react-description"
            )
            
            prompt = f"""You are a SQL expert. You can only query the table '{table_name}'. 
            Do not attempt to query any other tables. If the query requires joining with other tables, 
            inform the user that you can only work with the specified table.
            
            User Query: {query}
            
            Think through the steps to answer the query:
            1. What information do we need?
            2. What SQL query will get us that information?
            3. Execute the query and analyze the results
            4. Format the response in a clear way
            
            Let's solve this step by step:"""
            
            response = agent_executor.invoke({"input": prompt})
            return response["output"]
            
        except Exception as e:
            print(f"Error in process_query: {str(e)}")
            raise Exception(f"Error processing query: {str(e)}")

    def process_new_chat(self, df, jd_text, table_name):
        try:
            print("Step 1: Analyzing job description to determine required columns...")
            columns_response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": f"Analyze this job description and determine what columns should be in a candidates database table. Return ONLY a JSON array of column names that would be useful for storing candidate information relevant to this job. Include standard fields like name, email, phone, skills, experience, education, etc. Example format: [\"name\", \"email\", \"phone\", \"skills\", \"experience\", \"education\", \"linkedin\"].\n\nJob Description:\n{jd_text}"}],
                api_key=os.getenv('GOOGLE_API_KEY')
            )
            
            columns_content = columns_response.choices[0].message.content.strip()
            print(f"Debug: Raw columns response: {columns_content}")
            
            if columns_content.startswith('```json'):
                columns_content = columns_content[len('```json'):].lstrip()
            if columns_content.endswith('```'):
                columns_content = columns_content[:-len('```')].rstrip()
            
            try:
                columns = json.loads(columns_content)
                if not isinstance(columns, list) or not columns:
                    raise ValueError("Expected non-empty list")
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Failed to parse columns JSON, using default: {e}")
                columns = ["name", "email", "phone", "skills", "experience", "education", "linkedin"]
            
            print(f"Debug: Extracted columns: {columns}")
            
            if 'score' not in [col.lower() for col in columns]:
                columns.append("score")

            connection = self._get_db_connection()
            cursor = connection.cursor()
            
            try:
                # Create table if it doesn't exist
                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS "{table_name}" (
                    {', '.join([f'"{col}" TEXT' for col in columns])}
                )
                """
                cursor.execute(create_table_sql)
                connection.commit()
                
                processed_count = 0
                
                for index, row in df.iterrows():
                    try:
                        print(f"Processing candidate {index + 1}/{len(df)}")
                        
                        # Get both text and highlighted PDF path
                        resume_text, highlighted_pdf_path = self._download_and_extract_resume(row['pdf_url'])
                        print(f"Resume text extracted, length: {len(resume_text)} characters")
                        
                        print("Extracting candidate information...")
                        candidate_info = self._extract_candidate_info_for_jd(resume_text, jd_text, columns)
                        print(f"Candidate info extracted: {list(candidate_info.keys())}")
                        
                        print("Calculating match score...")
                        score = self._calculate_score(candidate_info, jd_text)
                        candidate_info['score'] = str(score)
                        print(f"Match score: {score}")
                        
                        # Add highlighted PDF path to database
                        if 'highlighted_pdf' not in columns:
                            columns.append('highlighted_pdf')
                            alter_table_sql = f'ALTER TABLE "{table_name}" ADD COLUMN "highlighted_pdf" TEXT'
                            cursor.execute(alter_table_sql)
                            connection.commit()
                        
                        insert_columns = ', '.join([f'"{col}"' for col in columns])
                        placeholders = ', '.join(['%s'] * len(columns))
                        insert_sql = f"INSERT INTO {table_name} ({insert_columns}) VALUES ({placeholders})"
                        
                        values = []
                        for col in columns:
                            if col == 'highlighted_pdf':
                                values.append(highlighted_pdf_path)
                            else:
                                value = candidate_info.get(col, '')
                                if value is None:
                                    values.append('')
                                else:
                                    values.append(str(value))
                        
                        print(f"Debug: Inserting candidate data...")
                        cursor.execute(insert_sql, values)
                        connection.commit()
                        processed_count += 1
                        print(f"Candidate {index + 1} processed successfully")
                        
                    except Exception as candidate_error:
                        print(f"Error processing candidate {index + 1}: {candidate_error}")
                        continue

                print(f"Processing completed. {processed_count} candidates processed successfully.")

            except Exception as e:
                connection.rollback()
                raise Exception(f"Database operation failed: {e}")
            finally:
                cursor.close()
                connection.close()
            
            return {"message": f"Processing completed successfully. {processed_count} candidates processed."}
            
        except Exception as e:
            raise Exception(f"Error processing new chat: {str(e)}")

    def _is_google_drive_url(self, url):
        return 'drive.google.com' in url

    def _get_google_drive_file_id(self, url):
        if 'id=' in url:
            return parse_qs(urlparse(url).query)['id'][0]
        elif '/d/' in url:
            return url.split('/d/')[1].split('/')[0]
        return None

    def _highlight_pdf(self, pdf_path, highlights):
        """
        Highlight important information in the PDF.
        highlights: dict with keys as categories and values as lists of text to highlight
        """
        try:
            # Read the original PDF
            pdf = PdfrwReader(pdf_path)
            output_path = os.path.join(HIGHLIGHTED_DIR, f"highlighted_{os.path.basename(pdf_path)}")
            
            # Create a new PDF with highlights
            c = canvas.Canvas(output_path)
            
            # Color mapping for different categories
            color_map = {
                'skills': yellow,
                'experience': green,
                'education': blue,
                'contact': red
            }
            
            for page_num, page in enumerate(pdf.pages):
                # Convert page to reportlab format
                page_obj = pagexobj(page)
                c.setPageSize((page_obj.BBox[2], page_obj.BBox[3]))
                
                # Draw the original page
                c.doForm(makerl(c, page_obj))
                
                # Add highlights
                for category, texts in highlights.items():
                    color = color_map.get(category, yellow)
                    for text in texts:
                        # Find text position and add highlight
                        # This is a simplified version - you might need to adjust coordinates
                        # based on your specific PDF structure
                        c.setFillColor(color)
                        c.setFillAlpha(0.3)  # Semi-transparent highlight
                        # Add highlight rectangle at text position
                        # You'll need to implement proper text position detection
                        c.rect(100, 100, 200, 20, fill=1)
                
                c.showPage()
            
            c.save()
            return output_path
        except Exception as e:
            print(f"Error highlighting PDF: {e}")
            return pdf_path

    def _download_and_extract_resume(self, pdf_url):
        try:
            temp_file_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}.pdf")

            if self._is_google_drive_url(pdf_url):
                file_id = self._get_google_drive_file_id(pdf_url)
                if not file_id:
                    raise Exception("Invalid Google Drive URL")
                
                gdown.download(f"https://drive.google.com/uc?id={file_id}", temp_file_path, quiet=False)
                
                if not os.path.exists(temp_file_path) or os.path.getsize(temp_file_path) == 0:
                    raise Exception("Failed to download file from Google Drive")
            else:
                response = requests.get(pdf_url)
                if response.status_code != 200:
                    raise Exception(f"Failed to download PDF: {response.status_code}")
                
                with open(temp_file_path, 'wb') as temp_file:
                    temp_file.write(response.content)

            # Extract text
            pdf_reader = PdfReader(temp_file_path)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text()
            
            # Extract and highlight important information
            highlights = {
                'skills': [],
                'experience': [],
                'education': [],
                'contact': []
            }
            
            # Use LLM to identify important information for highlighting
            highlight_prompt = f"""
            Analyze this resume and identify important information to highlight in these categories:
            - skills: Technical skills, programming languages, tools
            - experience: Key work experiences and achievements
            - education: Degrees, certifications, relevant coursework
            - contact: Contact information
            
            Resume Text:
            {text}
            
            Return ONLY a JSON object with arrays of text to highlight for each category.
            Example format: {{"skills": ["Python", "Machine Learning"], "experience": ["Led team of 5 developers"], "education": ["B.S. Computer Science"], "contact": ["john@email.com"]}}
            """
            
            response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": highlight_prompt}],
                api_key=os.getenv('GOOGLE_API_KEY')
            )
            
            try:
                highlight_data = json.loads(response.choices[0].message.content.strip())
                highlights.update(highlight_data)
            except:
                print("Failed to parse highlight data, continuing without highlights")
            
            # Create highlighted version
            highlighted_path = self._highlight_pdf(temp_file_path, highlights)
            
            # Clean up original temp file
            os.unlink(temp_file_path)
            
            return text, highlighted_path
                
        except Exception as e:
            if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception as cleanup_error:
                    print(f"Error cleaning up temporary file {temp_file_path}: {cleanup_error}")
            raise Exception(f"Error downloading or processing PDF: {str(e)}")

    def _extract_candidate_info(self, resume_text):
        try:
            response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": f"Extract candidate information from this resume:\n{resume_text}\nReturn ONLY a JSON object with the extracted information. Structure the JSON with relevant keys like 'name', 'email', 'phone', 'linkedin', 'skills', 'experience', 'education'. Ensure the output is ONLY the JSON object, for example: {{ \"name\": \"John Doe\", \"email\": \"john.doe@example.com\" }}. Do NOT include any other text or formatting before or after the JSON."}],
                api_key=os.getenv('GOOGLE_API_KEY')
            )
            
            llm_output_content = response.choices[0].message.content.strip()
            print(f"Debug: Raw LLM output for candidate info: {llm_output_content}")

            
            if llm_output_content.startswith('```json'):
                llm_output_content = llm_output_content[len('```json'):].lstrip()
            if llm_output_content.endswith('```'):
                llm_output_content = llm_output_content[:-len('```')].rstrip()

            return json.loads(llm_output_content)
        except json.JSONDecodeError as e:
             
             raise Exception(f"Error decoding JSON from LLM output for candidate info. Raw output: {llm_output_content}. Error: {e}")
        except Exception as e:
            raise Exception(f"Error extracting candidate info: {str(e)}")

    def _extract_candidate_info_for_jd(self, resume_text, jd_text, required_columns):
        
        try:
            columns_str = ', '.join(required_columns[:-1])
            
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
                api_key=os.getenv('GOOGLE_API_KEY')
            )
            
            llm_output_content = response.choices[0].message.content.strip()
            print(f"Debug: Raw LLM output for JD-specific candidate info: {llm_output_content[:200]}...")

            
            if llm_output_content.startswith('```json'):
                llm_output_content = llm_output_content[len('```json'):].lstrip()
            if llm_output_content.endswith('```'):
                llm_output_content = llm_output_content[:-len('```')].rstrip()

            candidate_info = json.loads(llm_output_content)
            
            
            for col in required_columns:
                if col != 'score' and col not in candidate_info:
                    candidate_info[col] = ''
            
            return candidate_info
            
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            print(f"Raw output: {llm_output_content}")
            
            default_info = {}
            for col in required_columns:
                if col != 'score':
                    default_info[col] = ''
            return default_info
        except Exception as e:
            raise Exception(f"Error extracting JD-specific candidate info: {str(e)}")

    def _calculate_score(self, candidate_info, jd_text):
        try:
            response = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": f"Calculate a match score (0-100) between this candidate and job description. Return ONLY the score number as a float.\nCandidate: {json.dumps(candidate_info)}\nJob Description: {jd_text}"}],
                api_key=os.getenv('GOOGLE_API_KEY')
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
                (name, reason)
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
            
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            tables_result = cursor.fetchall()
            
            tables = [row[0] for row in tables_result]
            
            cursor.close()
            connection.close()
            
            return tables
            
        except Exception as e:
            raise Exception(f"Error getting tables: {str(e)}")

    def get_table_insights(self, table_name):
        try:
            connection = self._get_db_connection()
            cursor = connection.cursor()
            
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = %s
            """, (table_name,))
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
            
            return {
                "columns": columns,
                "data": table_data
            }
            
        except Exception as e:
            raise Exception(f"Error getting table insights: {str(e)}")