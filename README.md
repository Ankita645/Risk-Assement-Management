# AI-Based Software Release Risk Prediction and Decision Support System

## Updated design
This version uses a Groq-hosted language model through **LangChain (`ChatGroq`)** for risk assessment. It does **not** train a Random Forest model and does **not** use a CSV dataset.

- `ml/static/index.html`: web form with six release fields plus a defect-description text area.
- `ml/api.py`: FastAPI endpoint that calls Groq, validates a High/Medium/Low result, and generates an Excel workbook containing all submitted inputs and assessment results.
- `ml/.env`: local configuration placeholder for `GROQ_API_KEY` and `GROQ_MODEL`. Replace the placeholder key with your own secret.
- `ml/.env.example`: template for setting up another environment.
- `ml/requirements.txt`: Python dependencies.
- `spring-backend/`: existing Java 17 / Spring Boot scaffold. The working browser demo in this iteration runs through FastAPI; Spring Boot is not required to run the AI assessment flow.

## Setup and run (macOS/Linux)
1. Install Python 3.10 or later.
2. Open a terminal in the `ml` folder.
3. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
4. Install dependencies:
   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
5. Open `ml/.env` and replace `your_groq_api_key_here` with your real Groq API key. Get a key from https://console.groq.com/keys. Keep the key private and never commit/share the `.env` file.
6. Start the app from inside the `ml` directory:
   ```bash
   uvicorn api:app --reload --port 8000
   ```
7. Open http://127.0.0.1:8000. API docs are at http://127.0.0.1:8000/docs and health status at http://127.0.0.1:8000/health.
8. Enter the release details and defect description, then click **Assess risk and generate Excel**. Review the classification and click **Download Excel report (.xlsx)**.

## Setup on Windows PowerShell
Run these commands from the `ml` directory:
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
uvicorn api:app --reload --port 8000
```
Before starting the app, edit `.env` with your Groq key.

## API endpoints
- `GET /` — browser interface.
- `GET /health` — service and configuration status; does not call Groq.
- `POST /assess` — accepts the release inputs and defect description, calls Groq, returns the assessment and an Excel download URL.
- `GET /reports/{assessment_id}.xlsx` — downloads the generated workbook.
- `GET /docs` — interactive FastAPI API documentation.

Example request body is in `ml/sample_request.json`. Reports are stored in memory for this prototype and disappear when the server restarts. For a multi-user/production system, persist assessment metadata and report files in a database or object storage, add authentication, rate limits, and audit logging.

## How the risk classification works
The system prompt instructs the LLM to consider changed files, changed lines, affected modules, unresolved defects, release criticality, recent release failures, and the defect description. It defines High/Medium/Low guidance and asks for a concise rationale and actionable recommendations. The model is configured with temperature 0 for more consistent outputs; an LLM can still vary, so results must be reviewed by a responsible human.

## Academic/demo notes
- This is an AI decision-support prototype, not a certified risk model or automatic release approval system.
- Output depends on the configured Groq model, supplied inputs, prompt, API availability, and model limits. Do not describe the result as a statistically validated prediction unless you later evaluate it against labelled real-world release outcomes.
- Do not submit credentials, customer data, or confidential production information to an external LLM. Use synthetic/anonymized examples for the seminar demo.
- The Groq API key is a secret. Keep it in `.env`, do not put it in frontend JavaScript, and do not upload `.env` to a public repository.
