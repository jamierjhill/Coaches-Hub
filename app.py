# app.py - Secured Tennis Match Organizer with Mobile Messages Only
from dotenv import load_dotenv
load_dotenv()

import os, random, csv, io, re
from datetime import timedelta
from collections import defaultdict
from flask import Flask, render_template, request, session, redirect

# Only import CSRF if available
try:
    from flask_wtf.csrf import CSRFProtect
    CSRF_AVAILABLE = True
except ImportError:
    print("Warning: Flask-WTF not installed. CSRF protection disabled.")
    CSRF_AVAILABLE = False

from utils import organize_matches

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev_key_UNSAFE_FOR_PRODUCTION")

# Initialize CSRF Protection only if available
if CSRF_AVAILABLE:
    csrf = CSRFProtect(app)
    # CSRF Configuration
    app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hour
    app.config['WTF_CSRF_SSL_STRICT'] = os.getenv("FLASK_ENV") == "production"

# Check if running in production
IS_PRODUCTION = os.getenv("FLASK_ENV") == "production"

# Session configuration with enhanced security
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = IS_PRODUCTION  # Only secure in production with HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB

@app.before_request
def make_session_permanent():
    session.permanent = True

@app.after_request
def add_security_headers(response):
    # Enhanced security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Only add HSTS in production
    if IS_PRODUCTION:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Updated CSP to allow Google Analytics
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://www.googletagmanager.com https://www.google-analytics.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "connect-src 'self' https://www.google-analytics.com https://analytics.google.com https://region1.google-analytics.com https://region1.analytics.google.com; "
        "img-src 'self' data: https://www.google-analytics.com https://www.googletagmanager.com"
    )
    
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

def sanitize_csv_field(field_value):
    """Sanitize CSV field to prevent formula injection"""
    if not field_value:
        return field_value
    
    field_value = str(field_value).strip()
    
    # Remove any quotes that might hide formulas
    field_value = field_value.strip('"\'')
    
    # If field starts with dangerous characters, prefix with single quote to neutralize
    if field_value and field_value[0] in ['=', '+', '-', '@', '\t', '\r']:
        field_value = "'" + field_value
    
    return field_value

def validate_player_name(name):
    """Enhanced player name validation with security checks"""
    if not name or len(name.strip()) == 0:
        return False, "Player name cannot be empty"
    
    name = name.strip()
    
    if len(name) > 50:
        return False, "Player name too long (max 50 characters)"
    
    # Check for dangerous CSV injection characters
    dangerous_chars = ['=', '+', '-', '@', '\t', '\r', '\n']
    if any(char in name for char in dangerous_chars):
        return False, "Player name contains potentially dangerous characters"
    
    # Allow only alphanumeric, spaces, hyphens, apostrophes, periods
    if not re.match(r"^[a-zA-Z0-9\s\-'.]+$", name):
        return False, "Player name contains invalid characters"
    
    # Additional checks
    if name.startswith(' ') or name.endswith(' '):
        return False, "Player name cannot start or end with spaces"
    
    if '  ' in name:  # Multiple consecutive spaces
        return False, "Player name cannot contain multiple consecutive spaces"
    
    return True, ""

def validate_csv_file(file):
    """Enhanced CSV file validation with security checks"""
    if not file:
        return False, "No file provided"
    
    if not file.filename:
        return False, "No file selected"
    
    # Check file extension
    if not file.filename.lower().endswith('.csv'):
        return False, "File must have .csv extension"
    
    # Check file size (already limited by MAX_CONTENT_LENGTH, but double-check)
    file.seek(0, 2)  # Seek to end
    size = file.tell()
    file.seek(0)  # Reset
    
    if size > 1024 * 1024:  # 1MB limit for CSV
        return False, "CSV file too large (max 1MB)"
    
    if size == 0:
        return False, "CSV file is empty"
    
    # Basic content validation
    try:
        # Read first 1KB to check if it's valid UTF-8 text
        file_sample = file.read(min(1024, size))
        file.seek(0)  # Reset
        
        try:
            file_sample.decode('utf-8')
        except UnicodeDecodeError:
            return False, "File does not appear to be a valid text file"
            
    except Exception:
        return False, "Error reading file"
    
    return True, ""

def sanitize_csv_content(content):
    """Sanitize entire CSV content to prevent formula injection"""
    lines = content.split('\n')
    sanitized_lines = []
    
    for line in lines:
        if not line.strip():  # Skip empty lines
            sanitized_lines.append(line)
            continue
            
        # Split by comma and sanitize each field
        fields = []
        # Simple CSV parsing - split by comma but handle quoted fields
        current_field = ""
        in_quotes = False
        
        for char in line:
            if char == '"' and (not current_field or current_field[-1] != '\\'):
                in_quotes = not in_quotes
                current_field += char
            elif char == ',' and not in_quotes:
                fields.append(sanitize_csv_field(current_field))
                current_field = ""
            else:
                current_field += char
        
        # Add the last field
        fields.append(sanitize_csv_field(current_field))
        sanitized_lines.append(','.join(fields))
    
    return '\n'.join(sanitized_lines)

def process_csv_upload_secure(file, existing_players):
    """Secure CSV upload processing with comprehensive validation"""
    try:
        # Validate file
        is_valid, error_msg = validate_csv_file(file)
        if not is_valid:
            return [], error_msg
        
        # Read and sanitize content
        content = file.read().decode("utf-8")
        content = sanitize_csv_content(content)
        
        # Parse CSV
        reader = csv.DictReader(io.StringIO(content))
        
        # Check for required columns
        required_columns = ['name', 'grade']
        if not reader.fieldnames or not all(col in reader.fieldnames for col in required_columns):
            return [], "CSV must have 'name' and 'grade' columns. Optional: 'max_rounds'"
        
        new_players = []
        added_count = 0
        skipped_count = 0
        errors = []
        
        for row_num, row in enumerate(reader, start=2):
            if row_num > 102:  # Limit to 100 players (plus header)
                break
            
            name = sanitize_csv_field(row.get("name", "")).strip()
            grade_str = sanitize_csv_field(row.get("grade", "")).strip()
            max_rounds_str = sanitize_csv_field(row.get("max_rounds", "")).strip()
            
            # Validate name with enhanced security
            is_valid_name, name_error = validate_player_name(name)
            if not is_valid_name:
                skipped_count += 1
                errors.append(f"Row {row_num}: {name_error}")
                continue
            
            # Validate grade
            try:
                grade = int(grade_str.strip("'\""))  # Remove any quotes added by sanitization
                if not (1 <= grade <= 4):
                    skipped_count += 1
                    errors.append(f"Row {row_num}: Grade must be between 1 and 4")
                    continue
            except (ValueError, TypeError):
                skipped_count += 1
                errors.append(f"Row {row_num}: Invalid grade format")
                continue
            
            # Validate max_rounds (optional)
            max_rounds = None
            if max_rounds_str:
                try:
                    max_rounds = int(max_rounds_str.strip("'\""))
                    if not (1 <= max_rounds <= 10):
                        skipped_count += 1
                        errors.append(f"Row {row_num}: Max rounds must be between 1 and 10")
                        continue
                except (ValueError, TypeError):
                    skipped_count += 1
                    errors.append(f"Row {row_num}: Invalid max_rounds format")
                    continue
            
            # Check for duplicates with existing players
            if any(p["name"].lower() == name.lower() for p in existing_players + new_players):
                skipped_count += 1
                errors.append(f"Row {row_num}: Player '{name}' already exists")
                continue
            
            # Create player dictionary
            player = {"name": name, "grade": grade}
            if max_rounds is not None:
                player["max_rounds"] = max_rounds
            
            new_players.append(player)
            added_count += 1
        
        # Prepare result message
        if added_count > 0:
            success_msg = f"Added {added_count} players"
            if skipped_count > 0:
                success_msg += f", skipped {skipped_count} invalid entries"
            return new_players, success_msg
        elif skipped_count > 0:
            return [], f"No valid players found. Skipped {skipped_count} entries with errors."
        else:
            return [], "No players found in CSV file"
        
    except Exception as e:
        return [], "Error processing CSV file. Please check format and try again."

def reshuffle_single_round(players, courts, match_type, round_to_reshuffle, existing_matchups, existing_rounds):
    """
    Reshuffle a specific round while preserving other rounds. More flexible algorithm that allows multiple reshuffles.
    """
    # Find players available for this round
    available_players = []
    for player in players:
        max_rounds = player.get('max_rounds', len(existing_rounds))
        if round_to_reshuffle <= max_rounds:
            available_players.append(player)
    
    if len(available_players) < (4 if match_type == "doubles" else 2):
        return None  # Not enough players for reshuffling
    
    # Shuffle available players for maximum randomness
    random.shuffle(available_players)
    
    # Track existing combinations from OTHER rounds (not the one we're reshuffling)
    existing_combinations = set()
    if match_type == "doubles":
        for court_matches in existing_matchups:
            for match, round_num in court_matches:
                if round_num != round_to_reshuffle and len(match) == 4:
                    # Store all possible team combinations
                    names = [p['name'] for p in match]
                    # Try different team splits
                    team1 = frozenset([names[0], names[1]])
                    team2 = frozenset([names[2], names[3]])
                    existing_combinations.add(frozenset([team1, team2]))
                    
                    team1 = frozenset([names[0], names[2]])
                    team2 = frozenset([names[1], names[3]])
                    existing_combinations.add(frozenset([team1, team2]))
                    
                    team1 = frozenset([names[0], names[3]])
                    team2 = frozenset([names[1], names[2]])
                    existing_combinations.add(frozenset([team1, team2]))
    else:  # singles
        for court_matches in existing_matchups:
            for match, round_num in court_matches:
                if round_num != round_to_reshuffle and len(match) == 2:
                    pair = frozenset([match[0]['name'], match[1]['name']])
                    existing_combinations.add(pair)
    
    # Generate new matches for this round
    new_round_matches = []
    used_players = set()
    
    def grade_distance(g1, g2):
        return abs(g1 - g2)
    
    def create_singles_match(candidates):
        """Create a singles match, preferring new combinations"""
        if len(candidates) < 2:
            return None
            
        best_pair = None
        best_score = float('inf')
        
        for i in range(len(candidates)):
            for j in range(i+1, len(candidates)):
                p1, p2 = candidates[i], candidates[j]
                pair_key = frozenset([p1['name'], p2['name']])
                
                # Score this pairing
                grade_diff = grade_distance(p1['grade'], p2['grade'])
                
                # Bonus for new combinations (but don't block old ones completely)
                novelty_bonus = 0 if pair_key in existing_combinations else -2
                
                score = grade_diff + novelty_bonus
                
                if score < best_score:
                    best_score = score
                    best_pair = [p1, p2]
        
        return best_pair
    
    def create_doubles_match(candidates):
        """Create a doubles match, preferring new combinations"""
        if len(candidates) < 4:
            return None
            
        best_group = None
        best_score = float('inf')
        
        # Try different combinations of 4 players
        for i in range(len(candidates)):
            for j in range(i+1, len(candidates)):
                for k in range(len(candidates)):
                    for l in range(k+1, len(candidates)):
                        if len(set([i, j, k, l])) != 4:
                            continue
                            
                        group = [candidates[i], candidates[j], candidates[k], candidates[l]]
                        
                        # Try this as team1 vs team2
                        team1 = [group[0], group[1]]
                        team2 = [group[2], group[3]]
                        
                        team1_avg = (team1[0]['grade'] + team1[1]['grade']) / 2
                        team2_avg = (team2[0]['grade'] + team2[1]['grade']) / 2
                        grade_diff = abs(team1_avg - team2_avg)
                        
                        # Check if this combination exists
                        team1_names = frozenset([team1[0]['name'], team1[1]['name']])
                        team2_names = frozenset([team2[0]['name'], team2[1]['name']])
                        match_key = frozenset([team1_names, team2_names])
                        
                        # Bonus for new combinations
                        novelty_bonus = 0 if match_key in existing_combinations else -3
                        
                        score = grade_diff + novelty_bonus
                        
                        if score < best_score:
                            best_score = score
                            best_group = group
        
        return best_group
    
    # Create matches for each court
    for court_index in range(courts):
        remaining_players = [p for p in available_players if p['name'] not in used_players]
        
        if match_type == "singles":
            match = create_singles_match(remaining_players)
            if match:
                new_round_matches.append((court_index, match))
                used_players.update([p['name'] for p in match])
        else:  # doubles
            match = create_doubles_match(remaining_players)
            if match:
                new_round_matches.append((court_index, match))
                used_players.update([p['name'] for p in match])
    
    return new_round_matches

@app.route("/", methods=["GET", "POST"])
@app.route("/index", methods=["GET", "POST"])
def index():
    """Main match organizer page with enhanced security."""
    
    # Get current session data
    players = session.get("players", [])
    courts = session.get("courts", 1)
    num_matches = session.get("num_matches", 1)
    match_type = session.get("match_type", "singles")
    
    matchups = session.get("matchups", [])
    player_match_counts = session.get("player_match_counts", {})
    rounds = session.get("rounds", {})
    error = None

    if request.method == "POST":
        # Update session configuration with validation
        try:
            courts_input = int(request.form.get("courts", courts))
            courts = max(1, min(20, courts_input))  # Limit to reasonable range
            
            num_matches_input = int(request.form.get("num_matches", num_matches))
            num_matches = max(1, min(10, num_matches_input))  # Limit to reasonable range
        except (ValueError, TypeError):
            error = "Invalid number format for courts or matches"
        
        match_type_input = request.form.get("match_type", match_type)
        if match_type_input in ["singles", "doubles"]:
            match_type = match_type_input
        
        session.update({
            "courts": courts,
            "num_matches": num_matches,
            "match_type": match_type
        })

        # Remove player
        if "remove_player" in request.form:
            name_to_remove = request.form.get("remove_player", "").strip()
            if name_to_remove:
                players = [p for p in players if p["name"] != name_to_remove]
                session["players"] = players
                # Clear matches when player is removed
                session.pop("matchups", None)
                session.pop("player_match_counts", None)
                session.pop("rounds", None)

        # CSV upload with enhanced security
        elif "upload_csv" in request.form:
            file = request.files.get("csv_file")
            new_players, message = process_csv_upload_secure(file, players)
            
            if new_players:
                players.extend(new_players)
                session["players"] = players
                # Clear matches when new players added
                session.pop("matchups", None)
                session.pop("player_match_counts", None)
                session.pop("rounds", None)
            else:
                error = message

        # Reset everything
        elif "reset" in request.form:
            session.clear()
            return redirect("/")

        # Add individual player with enhanced validation
        elif "add_player" in request.form:
            name = request.form.get("name", "").strip()
            grade_str = request.form.get("grade", "")
            max_rounds_str = request.form.get("max_rounds", "").strip()
            
            # Sanitize name input
            name = sanitize_csv_field(name)
            
            # Validate name
            is_valid_name, name_error = validate_player_name(name)
            if not is_valid_name:
                error = name_error
            else:
                try:
                    grade = int(grade_str)
                    if not (1 <= grade <= 4):
                        error = "Grade must be between 1 and 4"
                    # Check for duplicates
                    elif any(p["name"].lower() == name.lower() for p in players):
                        error = f"Player '{name}' already exists"
                    # Check player limit
                    elif len(players) >= 100:
                        error = "Maximum 100 players allowed"
                    else:
                        # Validate max_rounds (optional)
                        max_rounds = None
                        if max_rounds_str:
                            try:
                                max_rounds = int(max_rounds_str)
                                if not (1 <= max_rounds <= 10):
                                    error = "Max rounds must be between 1 and 10"
                                elif max_rounds > num_matches:
                                    error = f"Max rounds cannot exceed total rounds ({num_matches})"
                            except (ValueError, TypeError):
                                error = "Invalid max rounds format"
                        
                        if not error:
                            # Create player dictionary
                            player = {"name": name, "grade": grade}
                            if max_rounds is not None:
                                player["max_rounds"] = max_rounds
                            
                            players.append(player)
                            session["players"] = players
                            # Clear form by redirecting
                            return redirect("/")
                except (TypeError, ValueError):
                    error = "Invalid grade selected"

        # Reshuffle specific round with validation
        elif "reshuffle_round" in request.form:
            try:
                round_to_reshuffle = int(request.form.get("reshuffle_round"))
                
                if not (1 <= round_to_reshuffle <= 10):
                    error = "Invalid round number"
                elif matchups and rounds:
                    # Generate new matches for this round
                    new_round_matches = reshuffle_single_round(
                        players, courts, match_type, round_to_reshuffle, matchups, rounds
                    )
                    
                    if new_round_matches is not None:
                        # Remove old matches for this round from all courts
                        for court_index in range(len(matchups)):
                            matchups[court_index] = [
                                (match, round_num) for match, round_num in matchups[court_index]
                                if round_num != round_to_reshuffle
                            ]
                        
                        # Add new matches
                        for court_index, match in new_round_matches:
                            if court_index < len(matchups):
                                matchups[court_index].append((match, round_to_reshuffle))
                        
                        # Rebuild rounds structure
                        round_structure = defaultdict(list)
                        for court_index, court_matches in enumerate(matchups):
                            for match, round_num in court_matches:
                                round_structure[round_num].append((court_index + 1, match))
                        rounds = dict(sorted(round_structure.items()))
                        
                        # Recalculate match counts
                        player_match_counts = {p['name']: 0 for p in players}
                        for court_matches in matchups:
                            for match, round_num in court_matches:
                                for player in match:
                                    player_match_counts[player['name']] += 1
                        
                        # Update session
                        session.update({
                            "matchups": matchups,
                            "player_match_counts": player_match_counts,
                            "rounds": rounds
                        })
                        
                    else:
                        error = f"Unable to reshuffle round {round_to_reshuffle} - not enough available players"
                        
            except (ValueError, TypeError):
                error = "Invalid round number format"

        # Organize matches with validation
        elif "organize_matches" in request.form or "reshuffle" in request.form:
            min_players = 2 if match_type == "singles" else 4
            
            if len(players) < min_players:
                error = f"Need at least {min_players} players for {match_type} matches"
            elif len(players) > 100:
                error = "Too many players (max 100)"
            else:
                if "reshuffle" in request.form:
                    random.shuffle(players)

                try:
                    matchups, player_match_counts, opponent_averages, opponent_diff = organize_matches(
                        players, courts, match_type, num_matches
                    )

                    # Build round structure
                    round_structure = defaultdict(list)
                    for court_index, court_matches in enumerate(matchups):
                        for match, round_num in court_matches:
                            round_structure[round_num].append((court_index + 1, match))
                    rounds = dict(sorted(round_structure.items()))

                    session.update({
                        "matchups": matchups,
                        "player_match_counts": player_match_counts,
                        "rounds": rounds
                    })
                        
                except Exception as e:
                    error = "Error organizing matches. Please try again."

    return render_template(
        "index.html",
        players=players,
        matchups=matchups,
        courts=courts,
        num_matches=num_matches,
        match_type=match_type,
        player_match_counts=player_match_counts,
        rounds=rounds,
        error=error,
        csrf_available=CSRF_AVAILABLE
    )

@app.errorhandler(400)
def bad_request(error):
    return render_template('error.html', error_code=400, error_message="Bad Request"), 400

@app.errorhandler(404)
def not_found(error):
    return render_template('error.html', error_code=404, error_message="Page Not Found"), 404

@app.errorhandler(413)
def payload_too_large(error):
    return render_template('error.html', error_code=413, error_message="File Too Large"), 413

@app.errorhandler(500)
def server_error(error):
    return render_template('error.html', error_code=500, error_message="Internal Server Error"), 500

if __name__ == "__main__":
    # For development only - disable debug in production
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)