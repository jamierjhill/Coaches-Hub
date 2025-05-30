import os
import json
import random
import string
from uuid import uuid4
from datetime import datetime
from flask import Blueprint, render_template, redirect, request, session, flash
from flask_login import login_required, current_user
from user_utils import load_user

main_bp = Blueprint("main", __name__)

# === BULLETINS ===
def load_bulletin():
    coach = current_user.username
    filepath = f"data/bulletins/{coach}.json"
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r") as f:
        return json.load(f)

@main_bp.route("/")
def root():
    if current_user.is_authenticated:
        return redirect("/home")
    return redirect("/login")

@main_bp.route("/home")
@login_required
def home():
    try:
        user_data = load_user(current_user.username)
        postcode = user_data.get("default_postcode", "SW6 4UL") if user_data else "SW6 4UL"
        bulletin_messages = load_bulletin()
        
        # Initialize match organizer variables with defaults
        players = session.get("players", [])
        courts = session.get("courts", 1)
        num_matches = session.get("num_matches", 1)
        match_type = session.get("match_type", "singles")
        session_name = session.get("session_name", "")
        view_mode = session.get("view_mode", "court")
        matchups = session.get("matchups", [])
        player_match_counts = session.get("player_match_counts", {})
        opponent_averages = session.get("opponent_averages", {})
        opponent_diff = session.get("opponent_diff", {})
        rounds = session.get("rounds", {})
        
        return render_template(
            "home.html", 
            default_postcode=postcode, 
            bulletin_messages=bulletin_messages,
            players=players,
            courts=courts,
            num_matches=num_matches,
            match_type=match_type,
            matchups=matchups,
            player_match_counts=player_match_counts,
            session_name=session_name,
            opponent_averages=opponent_averages,
            opponent_diff=opponent_diff,
            rounds=rounds,
            view_mode=view_mode
        )
    except Exception as e:
        # FIXED: Instead of redirecting to login, log the error and return a simpler home page
        print(f"Error loading home page details: {e}")
        return render_template(
            "home.html", 
            default_postcode="SW6 4UL", 
            bulletin_messages=[],
            error=f"Some data couldn't be loaded. Please refresh or contact support if the issue persists."
        )

@main_bp.route("/bulletin")
@login_required
def bulletin():
    messages = load_bulletin()
    return render_template("bulletin.html", bulletin_messages=messages)

@main_bp.route("/post-bulletin", methods=["POST"])
@login_required
def post_bulletin():
    session["last_form_page"] = "/bulletin"
    message = request.form.get("message", "").strip()
    send_email = "send_email" in request.form
    if not message:
        return '', 204

    coach = current_user.username
    filepath = f"data/bulletins/{coach}.json"
    os.makedirs("data/bulletins", exist_ok=True)
    messages = []
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            messages = json.load(f)

    messages.append({
        "id": str(uuid4()),
        "text": message,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    })

    with open(filepath, "w") as f:
        json.dump(messages, f, indent=2)

    if send_email:
        send_bulletin_emails(coach, message)

    return '', 204

def send_bulletin_emails(coach, text):
    from app import mail
    from flask_mail import Message

    filepath = f"data/emails/{coach}.json"
    if not os.path.exists(filepath):
        return

    with open(filepath) as f:
        emails = json.load(f)

    subject = f"🎾 New Bulletin from Coach {coach.capitalize()}"

    for email in emails:
        body = (
            f"Hi there,\n\nCoach {coach.capitalize()} has posted a new bulletin:\n\n"
            f"{text}\n\n"
            f"If you no longer want to receive updates, you can unsubscribe in the player portal\n\n"
            f"— Coaches Hub"
        )
        try:
            msg = Message(subject=subject, recipients=[email], body=body)
            mail.send(msg)
        except Exception as e:
            print(f"❌ Failed to send to {email}: {e}")

@main_bp.route("/delete-bulletin/<msg_id>", methods=["POST"])
@login_required
def delete_bulletin(msg_id):
    coach = current_user.username
    filepath = f"data/bulletins/{coach}.json"
    if not os.path.exists(filepath):
        return redirect("/bulletin")

    with open(filepath, "r") as f:
        messages = json.load(f)
    messages = [msg for msg in messages if msg.get("id") != msg_id]

    with open(filepath, "w") as f:
        json.dump(messages, f, indent=2)

    return redirect("/bulletin")

@main_bp.route("/guide")
def guide():
    return render_template("coach_guide.html")

# === NOTES ===
# Update this function in blueprints/main.py
@main_bp.route("/notes", methods=["GET", "POST"])
@login_required
def notes():
    session["last_form_page"] = "/notes"
    username = current_user.username
    notes_path = f"notes/{username}.json"
    os.makedirs("notes", exist_ok=True)

    notes_list = []
    if os.path.exists(notes_path):
        with open(notes_path, "r") as f:
            # Check if we need to migrate from old format (list of strings)
            # to new format (list of objects with text and timestamp)
            content = json.load(f)
            if content and isinstance(content, list):
                if content and isinstance(content[0], str):
                    # Migrate old format to new format
                    notes_list = [
                        {
                            "id": str(uuid4()),
                            "text": note,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
                        } for note in content
                    ]
                    # Save migrated notes
                    with open(notes_path, "w") as f:
                        json.dump(notes_list, f, indent=2)
                else:
                    notes_list = content

    if request.method == "POST":
        if "note" in request.form:
            new_note = request.form["note"].strip()
            if new_note:
                notes_list.append({
                    "id": str(uuid4()),
                    "text": new_note,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
        elif "delete_note" in request.form:
            note_id = request.form["delete_note"].strip()
            notes_list = [n for n in notes_list if n.get("id") != note_id]

        with open(notes_path, "w") as f:
            json.dump(notes_list, f, indent=2)

        return '', 204

    # Sort notes by timestamp (newest first) before sending to template
    notes_list = sorted(notes_list, key=lambda x: x.get("timestamp", ""), reverse=True)
    return render_template("notes.html", notes=notes_list)

# === CONTACT ===
@main_bp.route("/contact", methods=["GET", "POST"])
def contact():
    session["last_form_page"] = "/contact"

    if request.method == "POST":
        from app import mail
        from flask_mail import Message

        name = request.form.get("name")
        email = request.form.get("email")
        message_body = request.form.get("message")

        msg = Message(
            subject=f"📩 Contact Form from {name}",
            sender=email,
            recipients=["coacheshubteam@gmail.com"],
            body=f"Name: {name}\nEmail: {email}\n\nMessage:\n{message_body}"
        )

        try:
            mail.send(msg)
            flash("✅ Message sent successfully!", "success")
        except Exception:
            flash("⚠️ Failed to send message. Please try again later.", "danger")

        return redirect("/home" if "go_home" in request.form else "/contact")

    return render_template("contact.html")


@main_bp.route("/delete-access-code/<code>", methods=["POST"])
@login_required
def delete_access_code(code):
    filepath = "data/session_codes.json"
    if not os.path.exists(filepath):
        return '', 404

    with open(filepath) as f:
        codes = json.load(f)

    if code in codes and codes[code].get("created_by") == current_user.username:
        del codes[code]
        with open(filepath, "w") as f:
            json.dump(codes, f, indent=2)
        return '', 204
    return '', 403

# Add this to blueprints/main.py
@main_bp.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy_policy.html")


@main_bp.route("/record-consent", methods=["POST"])
def record_consent():
    """Record user's consent preferences in the database"""
    if not current_user.is_authenticated:
        return jsonify({"success": False, "error": "Authentication required"}), 401
        
    try:
        data = request.get_json()
        consent_level = data.get("level")
        if consent_level not in ["essential", "all"]:
            return jsonify({"success": False, "error": "Invalid consent level"}), 400
            
        # Load user data
        user_data = load_user(current_user.username)
        if not user_data:
            return jsonify({"success": False, "error": "User not found"}), 404
            
        # Update user's consent record
        if "consent_records" not in user_data:
            user_data["consent_records"] = []
            
        # Add new consent record
        user_data["consent_records"].append({
            "timestamp": datetime.now().isoformat(),
            "level": consent_level,
            "ip_address": request.remote_addr,
            "user_agent": request.headers.get("User-Agent", "Unknown")
        })
        
        # Save updated user data
        save_user(user_data)
        
        return jsonify({"success": True})
        
    except Exception as e:
        print(f"Error recording consent: {e}")
        return jsonify({"success": False, "error": str(e)}), 500    
    
@main_bp.route("/learn-more")
def marketing_page():
    """Serve the marketing/landing page for the app."""
    return render_template("marketing.html")

# Add this route to blueprints/main.py

@main_bp.route("/access-codes", methods=["GET", "POST"])
@login_required
def access_codes():
    """Display and manage player access codes."""
    session["last_form_page"] = "/access-codes"
    
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("❌ Please enter a title for the access code.", "danger")
            return redirect("/access-codes")
        
        # Generate a unique 6-character code
        import string
        import random
        
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        # Ensure code is unique
        codes_file = "data/session_codes.json"
        os.makedirs("data", exist_ok=True)
        
        existing_codes = {}
        if os.path.exists(codes_file):
            with open(codes_file, "r") as f:
                existing_codes = json.load(f)
        
        # Keep generating until we get a unique code
        while code in existing_codes:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        # Save the new code
        new_code_data = {
            "title": title,
            "created_by": current_user.username,
            "created_at": datetime.now().strftime("%Y-%m-%d")
        }
        
        existing_codes[code] = new_code_data
        
        with open(codes_file, "w") as f:
            json.dump(existing_codes, f, indent=2)
        
        flash("✅ Access code created successfully!", "success")
        return redirect("/access-codes")
    
    # Load existing codes for this user
    codes_file = "data/session_codes.json"
    user_codes = {}
    
    if os.path.exists(codes_file):
        with open(codes_file, "r") as f:
            all_codes = json.load(f)
            # Filter codes created by current user
            user_codes = {
                code: data for code, data in all_codes.items() 
                if data.get("created_by") == current_user.username
            }
    
    return render_template("access_codes.html", codes=user_codes)