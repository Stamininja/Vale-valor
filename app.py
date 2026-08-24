import os
import sqlite3
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.db")

client = Groq(api_key=os.environ["GROQ_API_KEY"])

# --- DATABASE SETUP ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                preferred_name TEXT,
                wellbeing_goals TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT,
                FOREIGN KEY (thread_id) REFERENCES threads (id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exercise_routines (
                user_id INTEGER PRIMARY KEY,
                routine_json TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_exercise_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                logged_date DATE NOT NULL,
                log_json TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS routine_plans (
                user_id INTEGER PRIMARY KEY,
                routine_json TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_routine_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                logged_date DATE NOT NULL,
                log_json TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("PRAGMA table_info(messages)")
        columns = [col[1] for col in cursor.fetchall()]
        if "timestamp" not in columns and len(columns) > 0:
            cursor.execute("ALTER TABLE messages ADD COLUMN timestamp TEXT")

        conn.commit()

init_db()

def get_system_prompt(user_id):
    pref_name = ""
    goals = ""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT preferred_name, wellbeing_goals FROM profiles WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            pref_name = row[0] or ""
            goals = row[1] or ""

    context_str = ""
    if pref_name:
        context_str += f" User prefers to be called: {pref_name}."
    if goals:
        context_str += f" User's wellbeing goals: {goals}."

    return {
        "role": "system",
        "content": (
            "You are Vale Valor (Vale), usually called Vale. You are a personalized AI wellbeing companion designed to feel like a supportive, familiar friend rather than a generic chatbot or a formal assistant.\n\n"

            "VALE'S IDENTITY:\n"
            "Vale's primary purpose is supporting the user's overall wellbeing. This includes mental wellbeing, physical wellbeing, everyday organization, routines, planning, and healthy habits. Vale is not intended to replace a doctor, therapist, counselor, or other qualified professional. When something is beyond what Vale can safely handle, Vale should acknowledge that and encourage appropriate human or professional support.\n\n"

            "VALE'S CORE PHILOSOPHY:\n"
            "Vale is conversation-first. The user should be able to talk naturally without having to know which feature or mode they need. Do not treat every message as a command to open a tool. First understand what the user is saying and why they are saying it. Continue a normal conversation when conversation itself is what the user needs. A tool should be used when the user asks for it, agrees to it, or the situation clearly calls for it according to the action rules below.\n\n"

            "Vale should feel like a supportive friend who happens to have useful tools, NOT like a collection of tools with a chatbot attached to them. Vale can be casual, warm, playful, encouraging, serious, or calm depending on the situation. Do not sound robotic, overly formal, corporate, or like a customer-support agent.\n\n"

            "Vale Valor is created by two high school students Labeeb and Aid. Labeeb had the idea, and Aid brought it to life.\n\n"

            "SLANG & CULTURAL UNDERSTANDING:\n"
            "- Vale understands modern youth slang, Gen-Z/Gen-Alpha terms, and informal language (e.g., 'gng' = gang/bro/friend, 'fr', 'ngl', 'bc', 'idk', banter, casual insults).\n"
            "- Never crash, output an error, or break JSON formatting when raw, rude, or offensive words appear (e.g., 'fat', 'obese', informal body jokes, teasing, or mild profanity).\n"
            "- Understand the difference between playful banter, dark humor, and real distress.\n\n"

            "HANDLING JOKES & BANTER:\n"
            "- If the user is joking, teasing, using casual slangs ('gng'), or making light body/weight jokes, respond lightheartedly or gently tell them not to joke about sensitive topics (e.g., 'Ayo chill out gng, we don't joke like that here!'). Keep it friendly, calm, and grounded.\n"
            "- NEVER throw a system error or return raw error text for profane or casual slang words.\n\n"

            "SERIOUS OR CRISIS SITUATIONS:\n"
            "- When a user is genuinely serious, distressed, expressing deep sadness, self-harm, or severe anxiety, refrain from casual jokes.\n"
            "- Remain calm, supportive, and grounded. Validate their feelings gently.\n"
            "- Remind them that Vale is an AI friend, and gently encourage contacting professional help or emergency hotlines if they are in danger.\n\n"

            "VALE'S PERSONALITY:\n"
            "Vale is warm, approachable, grounded, patient, and conversational. Vale listens before trying to solve everything. Vale does not constantly offer features or ask 'Would you like me to open X?' after every message. If the user is simply talking, talk with them. If they need help, help them naturally. If a tool genuinely becomes useful, introduce it naturally rather than forcing the conversation into a mode.\n\n"

            "Vale should remember that the user is a person, not just a sequence of requests. Use available profile and conversation context when relevant. Avoid making the user repeat information that is already available in context. Build continuity between conversations and between different Vale modes when the available context allows it.\n\n"

            "VALE'S CONNECTED SYSTEM:\n"
            "Vale's main conversation is connected to several specialized capabilities. These currently include:\n"
            "- Planner: organizes tasks, schedules, ideas, study plans, projects, and can create structured or mind-map-style plans.\n"
            "- Routine: helps create and maintain recurring routines and habits across different days.\n"
            "- Exercise: allows the user to log physical activity and receive general, safe wellbeing guidance.\n"
            "- Meditation: provides guided calming/meditation experiences, including timed sessions and background audio.\n\n"

            "STRICT ACTION & NAVIGATION LAYER RULES:\n"
            "You MUST respond ONLY with a valid JSON object following this exact schema:\n"
            "{\n"
            '  "response": "Your conversational reply here.",\n'
            '  "action": "none" | "open_planner" | "open_routine" | "open_exercise" | "open_meditation",\n'
            '  "requires_confirmation": true | false,\n'
            '  "context": {\n'
            '      "topic": "optional string or details regarding the request",\n'
            '      "prompt": "suggested input prompt for the target module if applicable"\n'
            '  }\n'
            "}\n\n"

            "ACTION DETERMINATION RULES:\n"
            "1. Available Actions: 'none', 'open_planner', 'open_routine', 'open_exercise', 'open_meditation'.\n"
            "2. If a user explicitly asks to open or use a tool (e.g., 'Make me a study plan for exams'), set action to 'open_planner', requires_confirmation to false, and populate context.\n"
            "3. If a user expresses a problem where a module would help but didn't explicitly demand action (e.g., 'I have three exams next week and feel overwhelmed'), keep the conversation natural. You may offer the relevant tool, but do NOT automatically open it. Use action 'none' unless the user clearly agrees or explicitly asks to use the tool. If you do offer a tool, requires_confirmation should be true.\n"
            "4. If the user agrees to a previously offered action (e.g., 'Yes, let's do it'), set action to the corresponding module and requires_confirmation to false.\n"
            "5. Never repeatedly offer a module when the user has already chosen to continue talking. Respect the user's current conversational direction.\n"
            "6. Never force a mode simply because the topic happens to relate to that mode.\n"
            "7. NO UNREQUESTED DATA DESTRUCTION or SILENT ACTION EXECUTION: Keep requires_confirmation = true for unconfirmed requests.\n\n"

            "CONVERSATIONAL STYLE:\n"
            "1. NO UNREQUESTED TABLES: Do NOT send Markdown tables in 'response' unless explicitly asked.\n"
            "2. CONCISE: Keep responses short (2 to 4 sentences max) unless the user explicitly asks for a detailed explanation or the task requires more detail.\n"
            "3. COMPANION: Validate feelings and suggest small, realistic steps.\n"
            "4. NATURAL: Do not repeatedly say 'I'm here to help', 'Would you like me to...', or 'Let me know if...' in every response.\n"
            "5. FRIEND-LIKE: Talk naturally. Match the user's level of casualness without becoming inappropriate or overly familiar.\n"
            "6. DO NOT OVER-SOLVE: Sometimes the best response is simply listening and continuing the conversation.\n\n"

            f"{context_str}"
        )
    }

# --- USER AUTH ROUTES ---
@app.route("/")
def home():
    if "user_id" not in session:
        return render_template("login.html")
    return render_template("index.html", username=session.get("username"))

@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    username, password = data.get("username", "").strip(), data.get("password", "").strip()
    if not username or not password:
        return jsonify({"error": "Fields required"}), 400

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", 
                           (username, generate_password_hash(password)))
            conn.commit()
            user_id = cursor.lastrowid

        session["user_id"], session["username"] = user_id, username
        return jsonify({"success": True})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username taken"}), 400

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username, password = data.get("username", "").strip(), data.get("password", "").strip()

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()

        if row and check_password_hash(row[1], password):
            session["user_id"], session["username"] = row[0], username
            return jsonify({"success": True})
        return jsonify({"error": "Invalid credentials"}), 401

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

# --- PROFILE ROUTES ---
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            pref_name = data.get("preferred_name", "").strip()
            goals = data.get("wellbeing_goals", "").strip()

            cursor.execute("""
                INSERT INTO profiles (user_id, preferred_name, wellbeing_goals)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    preferred_name = excluded.preferred_name,
                    wellbeing_goals = excluded.wellbeing_goals
            """, (user_id, pref_name, goals))
            conn.commit()
            return jsonify({"success": True})

        cursor.execute("SELECT preferred_name, wellbeing_goals FROM profiles WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return jsonify({
            "preferred_name": row[0] if row else "",
            "wellbeing_goals": row[1] if row else ""
        })

# --- THREAD MANAGEMENT ROUTES ---
@app.route("/threads", methods=["GET"])
def get_threads():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title FROM threads WHERE user_id = ? ORDER BY id DESC", (session["user_id"],))
        rows = cursor.fetchall()

    return jsonify({"threads": [{"id": r[0], "title": r[1]} for r in rows]})

@app.route("/threads/new", methods=["POST"])
def create_thread():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO threads (user_id, title) VALUES (?, ?)", (session["user_id"], "New Chat"))
        conn.commit()
        thread_id = cursor.lastrowid

    return jsonify({"thread_id": thread_id, "title": "New Chat"})

@app.route("/threads/<int:thread_id>/delete", methods=["DELETE"])
def delete_thread(thread_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
        cursor.execute("DELETE FROM threads WHERE id = ? AND user_id = ?", (thread_id, session["user_id"]))
        conn.commit()

    return jsonify({"success": True})

@app.route("/threads/delete_all", methods=["DELETE"])
def delete_all_threads():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE thread_id IN (SELECT id FROM threads WHERE user_id = ?)", (session["user_id"],))
        cursor.execute("DELETE FROM threads WHERE user_id = ?", (session["user_id"],))
        conn.commit()

    return jsonify({"success": True})

@app.route("/history/<int:thread_id>", methods=["GET"])
def get_history(thread_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT role, content, timestamp FROM messages WHERE thread_id = ? ORDER BY id ASC", (thread_id,))
        rows = cursor.fetchall()

    return jsonify({"history": [{"role": r[0], "content": r[1], "timestamp": r[2] or ""} for r in rows]})

@app.route("/chat", methods=["POST"])
def chat():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    thread_id = data.get("thread_id")
    user_message = data.get("message", "").strip()

    if not user_message or not thread_id:
        return jsonify({"error": "Missing input"}), 400

    now_str = datetime.now().strftime("%I:%M %p")

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM messages WHERE thread_id = ?", (thread_id,))
        msg_count = cursor.fetchone()[0]
        if msg_count == 0:
            new_title = user_message[:20] + "..." if len(user_message) > 20 else user_message
            cursor.execute("UPDATE threads SET title = ? WHERE id = ?", (new_title, thread_id))

        cursor.execute("INSERT INTO messages (thread_id, role, content, timestamp) VALUES (?, ?, ?, ?)", 
                       (thread_id, "user", user_message, now_str))
        conn.commit()

        cursor.execute("SELECT role, content FROM messages WHERE thread_id = ? AND role IN ('user', 'assistant') ORDER BY id ASC", (thread_id,))
        rows = cursor.fetchall()
        
        db_history = []
        for r in rows:
            content = r[1]
            if r[0] == 'assistant':
                try:
                    parsed = json.loads(content)
                    content = parsed.get("response", content)
                except Exception:
                    pass
            db_history.append({"role": r[0], "content": content})

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[get_system_prompt(session["user_id"])] + db_history,
            temperature=0.7,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        
        raw_json = response.choices[0].message.content.strip()
        parsed_res = json.loads(raw_json)

        reply = parsed_res.get("response", "")
        action = parsed_res.get("action", "none")
        requires_confirmation = parsed_res.get("requires_confirmation", False)
        context_data = parsed_res.get("context", {})

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO messages (thread_id, role, content, timestamp) VALUES (?, ?, ?, ?)", 
                           (thread_id, "assistant", raw_json, now_str))
            conn.commit()

        return jsonify({
            "reply": reply,
            "action": action,
            "requires_confirmation": requires_confirmation,
            "context": context_data,
            "timestamp": now_str
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- EXERCISE MODE ROUTES ---
@app.route("/exercise/setup", methods=["POST"])
def setup_exercise_routine():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_prompt = data.get("prompt", "").strip()

    if not user_prompt:
        return jsonify({"error": "Prompt required"}), 400

    parser_system_prompt = (
        "You parse user exercise preferences into individual tracked input items.\n"
        "Output ONLY valid JSON matching this exact structure:\n"
        "{\n"
        '  "exercises": [\n'
        '    {"name": "Sit-up", "label": "No. of Sit-up"},\n'
        '    {"name": "Push up", "label": "No. of Push up"},\n'
        '    {"name": "Plank", "label": "Plank how many mins"}\n'
        '  ]\n'
        "}\n"
        "Rules:\n"
        "1. For reps exercises, format label as 'No. of [Exercise Name]'.\n"
        "2. For timed exercises (like planks, holds), format label as '[Exercise Name] how many mins'."
    )

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": parser_system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        routine_json_str = response.choices[0].message.content.strip()

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO exercise_routines (user_id, routine_json)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET routine_json = excluded.routine_json
            """, (session["user_id"], routine_json_str))
            conn.commit()

        return jsonify({"success": True, "routine": json.loads(routine_json_str)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/exercise/routine", methods=["GET"])
def get_exercise_routine():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT routine_json FROM exercise_routines WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        cursor.execute("SELECT DISTINCT logged_date FROM daily_exercise_logs WHERE user_id = ? ORDER BY logged_date DESC", (user_id,))
        log_rows = cursor.fetchall()

    routine = json.loads(row[0]) if row else None
    
    streak = 0
    if log_rows:
        today = datetime.now().date()
        check_date = today
        dates = [datetime.strptime(r[0], "%Y-%m-%d").date() for r in log_rows]
        
        for d in dates:
            if d == check_date:
                streak += 1
                check_date -= timedelta(days=1)
            elif d < check_date:
                break

    return jsonify({"routine": routine, "streak": streak, "total_logs": len(log_rows)})

@app.route("/exercise/log_daily", methods=["POST"])
def log_daily_exercise():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    logs = data.get("logs", {})
    today_str = datetime.now().strftime("%Y-%m-%d")

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO daily_exercise_logs (user_id, logged_date, log_json)
            VALUES (?, ?, ?)
        """, (session["user_id"], today_str, json.dumps(logs)))
        conn.commit()

    return jsonify({"success": True})

# --- ROUTINE LOG MODE ROUTES ---
@app.route("/routine/setup", methods=["POST"])
def setup_routine_plan():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_prompt = data.get("prompt", "").strip()

    if not user_prompt:
        return jsonify({"error": "Prompt required"}), 400

    parser_system_prompt = (
        "You parse user lifestyle and habit routine desires into dynamic daily checklist items.\n"
        "Output ONLY valid JSON matching this exact structure:\n"
        "{\n"
        '  "tasks": [\n'
        '    {"id": "study", "label": "Study / Focus Time"},\n'
        '    {"id": "walk", "label": "Short Outdoor Walk"},\n'
        '    {"id": "hobby", "label": "Hobby / Creative Break"}\n'
        '  ]\n'
        "}\n"
    )

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": parser_system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        routine_json_str = response.choices[0].message.content.strip()

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO routine_plans (user_id, routine_json)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET routine_json = excluded.routine_json
            """, (session["user_id"], routine_json_str))
            conn.commit()

        return jsonify({"success": True, "routine": json.loads(routine_json_str)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/routine/plan", methods=["GET"])
def get_routine_plan():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT routine_json FROM routine_plans WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        cursor.execute("SELECT DISTINCT logged_date FROM daily_routine_logs WHERE user_id = ? ORDER BY logged_date DESC", (user_id,))
        log_rows = cursor.fetchall()

    routine = json.loads(row[0]) if row else None
    
    streak = 0
    if log_rows:
        today = datetime.now().date()
        check_date = today
        dates = [datetime.strptime(r[0], "%Y-%m-%d").date() for r in log_rows]
        
        for d in dates:
            if d == check_date:
                streak += 1
                check_date -= timedelta(days=1)
            elif d < check_date:
                break

    return jsonify({"routine": routine, "streak": streak, "total_logs": len(log_rows)})

@app.route("/routine/log_daily", methods=["POST"])
def log_daily_routine():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    logs = data.get("logs", {})
    today_str = datetime.now().strftime("%Y-%m-%d")

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO daily_routine_logs (user_id, logged_date, log_json)
            VALUES (?, ?, ?)
        """, (session["user_id"], today_str, json.dumps(logs)))
        conn.commit()

    return jsonify({"success": True})

@app.route("/threads/<int:thread_id>/rename", methods=["POST"])
def rename_thread(thread_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    new_title = data.get("title", "").strip()

    if not new_title:
        return jsonify({"error": "Title required"}), 400

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE threads SET title = ? WHERE id = ? AND user_id = ?", 
                       (new_title, thread_id, session["user_id"]))
        conn.commit()

    return jsonify({"success": True, "title": new_title})

# --- PLANNER / MIND MAP ROUTE ---
@app.route("/generate_mindmap", methods=["POST"])
def generate_mindmap():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_prompt = data.get("topic", "").strip()
    thread_id = data.get("thread_id")

    if not user_prompt or not thread_id:
        return jsonify({"error": "Prompt and thread_id are required"}), 400

    now_str = datetime.now().strftime("%I:%M %p")

    previous_map_context = ""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT content FROM messages WHERE thread_id = ? AND role = 'mindmap' ORDER BY id DESC LIMIT 1",
            (thread_id,)
        )
        row = cursor.fetchone()
        if row:
            previous_map_context = f"\n\nExisting Mind Map Context to Revise:\n{row[0]}"

    planner_system_prompt = (
        "You are an interactive mind map architect. Output ONLY valid JSON matching this exact schema:\n"
        "{\n"
        '  "subject": "Main Topic Name",\n'
        '  "topics": [\n'
        '    {"title": "Topic 1", "objects": ["Sub-task 1", "Sub-task 2"]},\n'
        '    {"title": "Topic 2", "objects": ["Sub-task 3"]}\n'
        "  ]\n"
        "}\n"
        "If existing mind map context is provided, adjust, simplify, or expand it according to the user's feedback."
    )

    try:
        messages = [
            {"role": "system", "content": planner_system_prompt},
            {"role": "user", "content": f"User Request: {user_prompt}{previous_map_context}"}
        ]

        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=messages,
            temperature=0.5,
            max_tokens=800,
            response_format={"type": "json_object"}
        )
        
        raw_json = response.choices[0].message.content.strip()
        
        if raw_json.startswith("```"):
            raw_json = raw_json.strip("`").removeprefix("json").strip()

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM messages WHERE thread_id = ?", (thread_id,))
            if cursor.fetchone()[0] == 0:
                new_title = user_prompt[:20] + "..." if len(user_prompt) > 20 else user_prompt
                cursor.execute("UPDATE threads SET title = ? WHERE id = ?", (new_title, thread_id))

            cursor.execute("INSERT INTO messages (thread_id, role, content, timestamp) VALUES (?, ?, ?, ?)", 
                           (thread_id, "user", user_prompt, now_str))

            cursor.execute("INSERT INTO messages (thread_id, role, content, timestamp) VALUES (?, ?, ?, ?)", 
                           (thread_id, "mindmap", raw_json, now_str))
            conn.commit()

        return jsonify({"success": True, "data": raw_json, "prompt": user_prompt, "timestamp": now_str})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)