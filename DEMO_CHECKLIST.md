# Demo checklist — Groq LLM version

- [ ] Python 3.10+ is installed.
- [ ] A virtual environment is activated and `pip install -r requirements.txt` completes.
- [ ] `ml/.env` contains a valid `GROQ_API_KEY` and an enabled `GROQ_MODEL`.
- [ ] Run `uvicorn api:app --reload --port 8000` from the `ml` directory.
- [ ] `http://127.0.0.1:8000/health` returns `status: ok` and `groq_api_key_configured: true`.
- [ ] Open `http://127.0.0.1:8000`, enter all release fields and a defect description.
- [ ] Submit and verify that the UI shows High, Medium, or Low, rationale, recommendations, and model details.
- [ ] Download the `.xlsx` file and confirm it contains all inputs and AI assessment results.
- [ ] Try a second example with different values and description.
- [ ] Explain that the result is AI-generated decision support and that a human makes the release decision.
- [ ] Do not use real customer data or share the API key during the presentation.
