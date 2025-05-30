from .auth import auth_bp
from .main import main_bp
from .match import match_bp
from .calendar import calendar_bp
from .ai_tools import ai_tools_bp
from .settings import settings_bp
from .player import player_bp
from .admin import admin_bp
from .invoice import invoice_bp

# Ensure all blueprints are properly imported and listed
all_blueprints = [
    auth_bp,      # Authentication routes
    main_bp,      # Main dashboard and homepage
    match_bp,     # Match organization
    calendar_bp,  # Calendar functionality
    ai_tools_bp,  # AI tools for coaching
    settings_bp,  # User settings
    player_bp,    # Player portal access
    admin_bp,     # Admin dashboard
    invoice_bp    # Invoice management
]