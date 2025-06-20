from flask import Blueprint, jsonify, request, send_from_directory
from services.chat_service import ChatService
from services.insights_service import InsightsService
from services.peoples_api import PeoplesApi
import os
import pandas as pd
from werkzeug.utils import secure_filename
import tempfile
import requests
from PyPDF2 import PdfReader
import sqlite3
import json

chat_bp = Blueprint("chat", __name__)
chat_service = ChatService()
insights_service = InsightsService()
peoples_api = PeoplesApi()

HIGHLIGHTED_DIR = os.path.join(os.path.dirname(__file__), "..", "highlighted_resumes")


@chat_bp.route("/insights", methods=["GET"])
def get_insights():
    try:
        table_name = request.args.get("tableName")
        if not table_name:
            return jsonify({"error": "Missing tableName parameter"}), 400

        # Get insights for the specified table
        insights = insights_service.generate_insights(table_name)
        return jsonify(insights)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/candidate/<name>", methods=["GET"])
def get_candidate(name):
    try:
        candidate = chat_service.get_candidate_details_by_name(name)
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        return jsonify(candidate)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        table_name = data.get("tableName")
        query = data.get("query")
        user_id = data.get("user_id")

        if not table_name or not query:
            return jsonify({"error": "Missing tableName or query"}), 400

        result = chat_service.process_query(table_name, query, user_id)
        print("here with the rsult - ", result)
        return jsonify({"result": result["response"], "followups": result["followups"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/get-chats", methods=["GET"])
def getChats():
    try:
        table_name = request.args.get("tableName")
        user_id = request.args.get("user_id")

        if not table_name or not user_id:
            return jsonify({"error": "Missing tableName or user_id"}), 400

        chats = chat_service.get_all_chats_in_thread(table_name, user_id)
        return jsonify({"chats": chats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/send-email", methods=["GET"])
def sendEmail():
    try:
        # table_name = request.args.get("tableName")
        # user_id = request.args.get("user_id")

        # if not table_name or not user_id:
        #     return jsonify({"error": "Missing tableName or user_id"}), 400

        chats = chat_service.send_mail_to_candidates(
            "send an email to mansi.dwivedi@spit.ac.in saying 'Hey how are you now?'"
        )
        return jsonify({"chats": chats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/newChat", methods=["POST"])
def new_chat():
    try:
        if "csv" not in request.files or "pdf" not in request.files:
            return jsonify({"error": "Missing CSV or PDF file"}), 400

        csv_file = request.files["csv"]
        pdf_file = request.files["pdf"]
        table_name = request.form.get("tableName")

        if not table_name:
            return jsonify({"error": "Missing tableName"}), 400

        temp_dir = tempfile.mkdtemp()
        csv_path = os.path.join(temp_dir, secure_filename(csv_file.filename))
        pdf_path = os.path.join(temp_dir, secure_filename(pdf_file.filename))

        csv_file.save(csv_path)
        pdf_file.save(pdf_path)

        df = pd.read_csv(csv_path)

        pdf_reader = PdfReader(pdf_path)
        jd_text = ""
        for page in pdf_reader.pages:
            jd_text += page.extract_text()

        result = chat_service.process_new_chat(df, jd_text, table_name)

        os.remove(csv_path)
        os.remove(pdf_path)
        os.rmdir(temp_dir)

        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/gettables", methods=["GET"])
def get_tables():
    try:
        tables = chat_service.get_all_tables()
        return jsonify({"tables": tables})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/chat/2", methods=["POST"])
def chat_to_elastic():
    try:
        data = request.get_json()
        prompt = data.get("prompt", "")
        if not prompt:
            return jsonify({"error": "Missing prompt"}), 400

        gemini_instruction = """
        You are an expert in Elasticsearch. Given the following user prompt, generate a JSON Elasticsearch query in this STRICT format only:
        below is a example of the query format:
        {
        "query": {
            "bool": {
                "must": [
                    {"term": {"location_country": "mexico"}},
                    {"term": {"job_title_role": "health"}},
                    {"exists": {"field": "phone_numbers"}}
            ]
            }
        }
        }

        - Only return the JSON in the above format, filling in the query as needed based on the prompt.
        - Do not add any explanation or extra text.
        - If the prompt is empty, return the default query as above.
        - note your context is the peoples datalabs Person schema for your fields
        Prompt: 
        """

        gemini_instruction = gemini_instruction + prompt

        from langchain_google_genai import ChatGoogleGenerativeAI
        import os
        import json

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            temperature=0,
        )
        response = llm.invoke(gemini_instruction)
        content = response.content if hasattr(response, "content") else str(response)
        if content.strip().startswith("```json"):
            content = content.strip()[7:]
        if content.strip().startswith("```"):
            content = content.strip()[3:]
        if content.strip().endswith("```"):
            content = content.strip()[:-3]
        content = content.strip()
        try:
            elastic_query = json.loads(content)
        except Exception:
            elastic_query = content
        print("Elastic Query:", elastic_query)
        # Call People Data Labs API with the elastic query
        peoples_data = peoples_api.fetch_peoples_data(elastic_query)
        return jsonify(peoples_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@chat_bp.route("/highlighted_resume/<filename>", methods=["GET"])
def get_highlighted_resume(filename):
    try:
        return send_from_directory(HIGHLIGHTED_DIR, filename)
    except Exception as e:
        return jsonify({"error": str(e)}), 404
