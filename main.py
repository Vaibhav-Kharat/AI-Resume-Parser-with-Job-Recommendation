import requests
from fastapi import Form
from fastapi import FastAPI, Request, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import os
import re
import json
import shutil
import httpx  # for url

from pdfminer.high_level import extract_text
import spacy
from docx import Document
import textract
import google.generativeai as genai
from tempfile import NamedTemporaryFile

# Set up FastAPI
app = FastAPI()
app.mount("/resumes", StaticFiles(directory="resumes"), name="resumes")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Create resumes directory if not exists
UPLOAD_FOLDER = 'resumes'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load spaCy English model
nlp = spacy.load('en_core_web_sm')

# Configure Gemini
genai.configure(api_key="AIzaSyCOtvmt2fy2Wm4NMrgGi-Dwkf0xndECW1s")


# Helper: Extract text from DOCX
def extract_text_from_docx(file_path):
    try:
        doc = Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        print(f"Error reading DOCX: {e}")
        return ""


# Helper: Extract text from DOC (using textract)
def extract_text_from_doc(file_path):
    try:
        return textract.process(file_path).decode('utf-8')
    except Exception as e:
        print(f"Error reading DOC: {e}")
        return ""


def extract_resume_data(file_path):
    text = extract_text(file_path).strip()
    doc = nlp(text)
    lines = text.splitlines()
    return {}


def extract_with_gemini(resume_text):
    with open("job_postings.json", "r") as f:
        all_jobs = json.load(f)

    job_data_str = json.dumps(all_jobs, indent=2)
    prompt = f"""
You are an intelligent job recommendation engine. Based on the user's resume below and the list of job postings, do the following:

1. Extract:
- Full Name
- Email
- Phone Number
- Qualification
- Years of Experience (as a number)
- Career Objective
- List of Technical Skills (comma-separated)
- Location

2. Then, recommend jobs where:
- The user's experience fits the job's experience range (e.g. 3–5 years)
- The user has matching skills (at least 1–2 relevant skills)

Return the result in this JSON format:
{{
  "name": "...",
  "email": "...",
  "phone": "...",
  "qualification": "...",
  "experience": "...",
  "objective": "...",
  "skills": "...",
  "location": "...",
  "recommended_jobs": [
    {{
      "id": 1,
      "title": "...",
      "qualification": "...",
      "skills_required": ["...", "..."],
      "experience": "...",
      "why_recommended": "..."
    }},
    ...
  ]
}}

Resume Text:
\"\"\"
{resume_text}
\"\"\"
Job Postings:
```json
{job_data_str}
"""

    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)
    print("Gemini raw response:\n", response.text)

    raw_text = response.text.strip()
    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
    cleaned = re.sub(r"\n```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except Exception as e:
        print("Error parsing JSON from Gemini:", e)
        print("Cleaned output was:\n", cleaned)
        return {"raw": cleaned}


def get_recommended_jobs_by_skills_in_order(skills, all_jobs):
    matched_jobs = []
    seen_ids = set()

    for skill in skills:
        for job in all_jobs:
            if (
                job['id'] not in seen_ids and
                any(skill.lower() == s.lower() for s in job['skills_required'])
            ):
                matched_jobs.append(job)
                seen_ids.add(job['id'])

    return matched_jobs


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    with open('job_postings.json', 'r') as f:
        all_jobs = json.load(f)
    return templates.TemplateResponse("index.html", {"request": request, "all_jobs": all_jobs})


@app.post("/upload_url", response_class=HTMLResponse)
async def upload_resume_from_url(request: Request, resume_url: str = Form(...)):
    try:
        # Convert Google Drive view link to direct download link
        if "drive.google.com" in resume_url:
            match = re.search(r"/d/([a-zA-Z0-9_-]+)", resume_url)
            if match:
                file_id = match.group(1)
                resume_url = f"https://drive.google.com/uc?export=download&id={file_id}"

        filename = filename = "resume_from_url.pdf"
        file_path = os.path.join(UPLOAD_FOLDER, filename)

        # binary stream
        response = requests.get(resume_url, stream=True)
        if response.status_code != 200:
            return HTMLResponse("Failed to download file from URL.", status_code=400)

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        ext = os.path.splitext(filename)[-1].lower()
        if ext == ".pdf":
            resume_text = extract_text(file_path)
        elif ext == ".docx":
            resume_text = extract_text_from_docx(file_path)
        elif ext == ".doc":
            resume_text = extract_text_from_doc(file_path)
        else:
            return HTMLResponse("Unsupported file format", status_code=400)

        gpt_data = extract_with_gemini(resume_text)

    except Exception as e:
        print("Error downloading or processing resume from URL:", e)
        gpt_data = {"error": str(e)}

    return templates.TemplateResponse("results.html", {
        "request": request,
        "gpt_data": gpt_data,
    })


@app.post("/upload", response_class=HTMLResponse)
async def upload_resume(request: Request, resume: UploadFile = File(...)):
    if not resume.filename:
        return HTMLResponse("No file selected.", status_code=400)

    file_path = os.path.join(UPLOAD_FOLDER, resume.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(resume.file, buffer)

    # Determine file type and extract text accordingly
    try:
        ext = os.path.splitext(resume.filename)[-1].lower()
        if ext == ".pdf":
            resume_text = extract_text(file_path)
        elif ext == ".docx":
            resume_text = extract_text_from_docx(file_path)
        elif ext == ".doc":
            resume_text = extract_text_from_doc(file_path)
        else:
            return HTMLResponse("Unsupported file format", status_code=400)

        gpt_data = extract_with_gemini(resume_text)
    except Exception as e:
        gpt_data = None
        print("AI extraction failed:", e)

    with open('job_postings.json', 'r') as f:
        all_jobs = json.load(f)

    extracted_skills = []
    if gpt_data and 'skills' in gpt_data and isinstance(gpt_data['skills'], str):
        extracted_skills = [s.strip().lower()
                            for s in gpt_data['skills'].split(",")]

    recommended_jobs = get_recommended_jobs_by_skills_in_order(
        extracted_skills, all_jobs)

    return templates.TemplateResponse("results.html", {
        "request": request,
        "gpt_data": gpt_data,
        "recommended_jobs": recommended_jobs
    })
