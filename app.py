from flask import Flask, request, render_template
import os
import re
from pdfminer.high_level import extract_text
import spacy
import json
import google.generativeai as genai
import os
# Configure Gemini
genai.configure(api_key="AIzaSyD7sGfpOEDRArRSAcNMUR5WMM-g4mGKOKY")

app = Flask(__name__)
UPLOAD_FOLDER = 'resumes'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load spaCy English model
nlp = spacy.load('en_core_web_sm')


def extract_resume_data(file_path):
    text = extract_text(file_path).strip()
    doc = nlp(text)
    lines = text.splitlines()

    # ------------------------
    # Extract SKILLS section
    skills_section_lines = []
    collecting_skills = False

    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            continue

    return {
        # "name": name.strip(),
        # "email": email.strip(),
        # "mobile_number": phone.strip(),
        # "total_experience": experience.strip(),
        # "technical_skills": found_skills,
        # "objective": objective,
        # "recommended_jobs": recommended_jobs
    }


def extract_with_gemini(resume_text):
    prompt = f"""
You are a resume parsing assistant. Extract the following details from the resume text below:
- Full Name
- Email
- Phone Number
- Years of Experience
- Career Objective
- List of Technical Skills (comma-separated)

Return the response in valid JSON format with keys:
name, email, phone, experience, objective, skills.

Resume Text:
\"\"\"
{resume_text}
\"\"\"
"""

    model = genai.GenerativeModel("gemini-1.5-flash")

    response = model.generate_content(prompt)
    raw_text = response.text.strip()

    # cleaning the data which is coming in json format to html text
    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
    cleaned = re.sub(r"\n```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except:
        return {"raw": cleaned}


def get_recommended_jobs_by_skills_in_order(skills, all_jobs):
    matched_jobs = []
    seen_ids = set()

    for skill in skills:
        for job in all_jobs:
            if (
                job['id'] not in seen_ids
                and any(skill.lower() == s.lower() for s in job['skills_required'])
            ):
                matched_jobs.append(job)
                seen_ids.add(job['id'])

    return matched_jobs


@app.route('/')
def index():
    with open('job_postings.json', 'r') as f:
        all_jobs = json.load(f)
    return render_template('index.html', all_jobs=all_jobs)


@app.route('/upload', methods=['POST'])
def upload_resume():
    if 'resume' not in request.files:
        return "No file uploaded."
    file = request.files['resume']

    if file.filename == '':
        return "No file selected."

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(file_path)

    data = extract_resume_data(file_path)

    try:
        resume_text = extract_text(file_path)
        gpt_data = extract_with_gemini(resume_text)  # or extract_with_gpt()
    except Exception as e:
        gpt_data = None
        print("AI extraction failed:", e)

     #  Load job postings
    with open('job_postings.json', 'r') as f:
        all_jobs = json.load(f)

     #  Extract skills from Gemini response and split by comma
    extracted_skills = []
    if gpt_data and 'skills' in gpt_data and isinstance(gpt_data['skills'], str):
        extracted_skills = [s.strip().lower()
                            for s in gpt_data['skills'].split(",")]

    #  Get matching jobs based on ordered skills
    recommended_jobs = get_recommended_jobs_by_skills_in_order(
        extracted_skills, all_jobs)

    return render_template(
        'results.html',
        gpt_data=gpt_data,
        recommended_jobs=recommended_jobs  # pass it to the template
    )


if __name__ == '__main__':
    app.run(debug=True)
