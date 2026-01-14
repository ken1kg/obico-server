import re
import logging
import os
import time
import hmac
import hashlib
import base64
import configparser
from django.utils import translation
from django.conf import settings

from lib.syndicate import syndicate_from_request, settings_for_syndicate


RE_TSD_APP_PLATFORM = re.compile(r'TSDApp-(?P<platform>\w+)')

def additional_context_export(request):

    # --- 1. Existing Platform Detection Logic ---
    platform = request.GET.get('platform', None)      # Allow get parameter to override for debugging purpose
    if not platform:
        m = RE_TSD_APP_PLATFORM.match(request.headers.get('X-TSD-Platform', '') or request.headers.get('user-agent', ''))
        platform = m.groupdict()['platform'] if m else ''

    # --- 2. Existing Syndicate/Branding Logic ---
    # TODO: JusPrin syndicate hack so that we can set branding without add a syndicate to the DB
    user_agent = request.META.get('HTTP_USER_AGENT', 'Not provided')
    if user_agent.startswith("JusPrin"):
        syndicate_name = 'jusprin'
    else:
        syndicate_name = syndicate_from_request(request).name

    syndicate_settings = settings_for_syndicate(syndicate_name)
    syndicate_settings['name'] = syndicate_name

    # --- 3. NEW: Dynamic TURN Configuration (turn.cfg) ---
    
    # Initialize with values from the syndicate settings (settings.py defaults)
    turn_server = syndicate_settings.get('turn_server')
    turn_user = syndicate_settings.get('turn_user', 'obico')
    turn_password = syndicate_settings.get('turn_password')
    turn_port = 80  # Default port is 80
    turn_secret = None

    # Check for overrides in turn.cfg
    config_path = os.path.join(settings.BASE_DIR, 'turn.cfg')
    
    if os.path.exists(config_path):
        try:
            config = configparser.ConfigParser()
            config.read(config_path)
            
            if 'turn' in config:
                turn_cfg = config['turn']
                
                # Only override if 'server' is explicitly set in the file
                if turn_cfg.get('server'):
                    turn_server = turn_cfg.get('server')
                    turn_port = turn_cfg.getint('port', fallback=80)
                    
                    # Option A: Check for Secret (REST API Auth)
                    if turn_cfg.get('secret'):
                        turn_secret = turn_cfg.get('secret')
                        turn_user = turn_cfg.get('username', fallback='obico')
                    
                    # Option B: Check for Static Creds (Fallback if no secret)
                    elif turn_cfg.get('username') and turn_cfg.get('password'):
                        turn_user = turn_cfg.get('username')
                        turn_password = turn_cfg.get('password')
                        
        except Exception as e:
            # Fail silently and use defaults/settings.py if config is malformed
            logging.error(f"Error reading turn.cfg: {e}")

    # Generate Dynamic Credentials (if using auth-secret/REST API)
    if turn_server and turn_secret:
        # Create token valid for 24 hours
        expiry_time = int(time.time()) + 86400
        
        # Format: timestamp:username
        raw_user = turn_user
        turn_user = "{}:{}".format(expiry_time, raw_user)
        
        # Format: Base64(HMAC-SHA1(secret, username))
        hashed = hmac.new(turn_secret.encode('utf-8'), turn_user.encode('utf-8'), hashlib.sha1)
        turn_password = base64.b64encode(hashed.digest()).decode('utf-8')

    # Update the syndicate_settings dictionary with the final TURN values
    syndicate_settings['turn_server'] = turn_server
    syndicate_settings['turn_port'] = turn_port
    syndicate_settings['turn_user'] = turn_user
    syndicate_settings['turn_password'] = turn_password

    # --- 4. Existing Language Logic & Return ---
    language = translation.get_language_from_request(request).split('-')[0] # ISO 639-1 standard is language_code-country_code

    return {
        'page_context': {
            'app_platform': platform,
            'syndicate': syndicate_settings,
            'language': language,
        }
    }


def additional_settings_export(request):
    settings_dict = {
        'TWILIO_COUNTRY_CODES': settings.TWILIO_COUNTRY_CODES,
    }

    return settings_dict
