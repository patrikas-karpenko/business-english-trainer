from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
import re

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/evaluate-write-in", response_class=HTMLResponse)
async def evaluate_write_in(q1_answer: str = Form(...), q2_answer: str = Form(...)):
    score = 0
    feedback = ""
    if q1_answer.strip().lower() == "reader":
        score += 50
        feedback += "<p class='text-green-700'>✔️ Q1: Correct! 'reader'</p>"
    else:
        feedback += "<p class='text-red-600'>❌ Q1: Incorrect. The person reading is the 'reader'.</p>"
        
    if q2_answer.strip().lower() == "purpose":
        score += 50
        feedback += "<p class='text-green-700'>✔️ Q2: Correct! 'purpose'</p>"
    else:
        feedback += "<p class='text-red-600'>❌ Q2: Incorrect. The reason you write is the 'purpose'.</p>"
        
    return f"<div class='mt-4 p-4 border border-blue-200 bg-blue-50 rounded-lg shadow-sm'><strong>Score: {score}</strong>{feedback}</div>"

@app.post("/evaluate-reading", response_class=HTMLResponse)
async def evaluate_reading(q1: str = Form(...), q2: str = Form(...), q3: str = Form(...)):
    correct = {"q1": "B", "q2": "A", "q3": "B"}
    score = sum([33 for k, v in correct.items() if locals()[k] == v])
    if score == 99: score = 100
    
    fb = ""
    fb += "<p class='text-green-700'>✔️ Q1 Correct</p>" if q1 == "B" else "<p class='text-red-600'>❌ Q1 Incorrect</p>"
    fb += "<p class='text-green-700'>✔️ Q2 Correct</p>" if q2 == "A" else "<p class='text-red-600'>❌ Q2 Incorrect</p>"
    fb += "<p class='text-green-700'>✔️ Q3 Correct</p>" if q3 == "B" else "<p class='text-red-600'>❌ Q3 Incorrect</p>"
    
    return f"<div class='mt-4 p-4 border border-blue-200 bg-blue-50 rounded-lg shadow-sm'><strong>Score: {score}/100</strong>{fb}</div>"

@app.post("/evaluate-extraction", response_class=HTMLResponse)
async def evaluate_extraction(delivery_date: str = Form(...), invoice_total: str = Form(...)):
    score = 0
    fb = ""
    clean_date = delivery_date.strip()
    if clean_date == "2026-10-26":
        score += 50
        fb += "<p class='text-green-700'>✔️ Date: Correct (2026-10-26).</p>"
    else:
        fb += "<p class='text-red-600'>❌ Date: Format exactly as YYYY-MM-DD.</p>"
        
    clean_invoice = re.sub(r'[^\d]', '', invoice_total)
    if clean_invoice == "2400":
        score += 50
        fb += "<p class='text-green-700'>✔️ Invoice: Correct (2400).</p>"
    else:
        fb += "<p class='text-red-600'>❌ Invoice: Incorrect.</p>"
        
    return f"<div class='mt-4 p-4 border border-blue-200 bg-blue-50 rounded-lg shadow-sm'><strong>Score: {score}/100</strong>{fb}</div>"

@app.post("/evaluate-email", response_class=HTMLResponse)
async def evaluate_email(student_text: str = Form(...), scenario_id: str = Form(...)):
    # Mock LLM Response for Cloud Testing
    return f"""
    <div class="mt-6 p-6 border border-indigo-200 bg-indigo-50 rounded-xl shadow-sm animate-fade-in">
        <h3 class="font-bold text-indigo-900 text-lg mb-2">AI Tutor Feedback</h3>
        <div class="text-gray-800"><em>(LLM API not connected. Mock Response):</em> Your email structure looks good, but remember to be more concise. Score: 8/10.</div>
    </div>
    """

@app.post("/evaluate-stress-test", response_class=HTMLResponse)
async def evaluate_stress_test(chat_reply: str = Form(...)):
    if chat_reply == "TIMEOUT_FAIL":
        return """
        <div class="flex flex-col space-y-2 mt-4 animate-fade-in">
            <div class="self-start text-sm text-red-700 font-medium max-w-[80%] bg-red-50 border border-red-200 p-3 rounded-r-lg rounded-bl-lg shadow-sm">
                🔴 Time's up! In live business chat, taking too long leaves the manager hanging. Try again.
            </div>
        </div>
        """
        
    # Mock LLM Response for Cloud Testing
    return f"""
    <div class="flex flex-col space-y-2 mt-4 animate-fade-in">
        <div class="self-end bg-indigo-600 text-white p-3 rounded-l-lg rounded-br-lg max-w-[80%]">
            {chat_reply}
        </div>
        <div class="self-start text-sm text-gray-700 font-medium max-w-[80%] bg-white border border-gray-200 p-2 rounded-r-lg rounded-bl-lg shadow-sm">
            AI: 🟢 <em>(Simulated Feedback)</em> Good brevity and professional tone.
        </div>
    </div>
    """
