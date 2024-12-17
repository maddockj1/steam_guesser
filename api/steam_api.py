import requests
import pandas as pd
from datetime import datetime
import time
from collections import deque
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
STEAM_API_KEY = os.getenv('STEAM_API_KEY')

if not STEAM_API_KEY:
    raise ValueError("Steam API key not found in .env file")

# Rate limiting settings
CALLS_PER_MINUTE = 100
STORE_CALLS_PER_MINUTE = 10
CALL_HISTORY_WINDOW = 60
MAX_GAMES = 10

# Rate limiting queues
api_call_times = deque(maxlen=CALLS_PER_MINUTE)
store_call_times = deque(maxlen=STORE_CALLS_PER_MINUTE)

def wait_for_rate_limit(call_times, calls_per_minute):
    """Implement rate limiting"""
    now = time.time()
    
    while call_times and call_times[0] < now - CALL_HISTORY_WINDOW:
        call_times.popleft()
    
    if len(call_times) >= calls_per_minute:
        wait_time = call_times[0] - (now - CALL_HISTORY_WINDOW)
        if wait_time > 0:
            print(f"Rate limit reached, waiting {wait_time:.2f} seconds...")
            time.sleep(wait_time)
    
    call_times.append(now)

def get_game_name(app_id):
    """Get game name from Steam Store API"""
    try:
        store_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
        store_response = requests.get(store_url)
        store_data = store_response.json()
        
        if store_data and str(app_id) in store_data:
            return store_data[str(app_id)].get('data', {}).get('name', f"Game {app_id}")
        return f"Game {app_id}"
        
    except Exception as e:
        return f"Game {app_id}"

def get_current_players(app_id):
    """Get current player count for a specific game"""
    try:
        wait_for_rate_limit(api_call_times, CALLS_PER_MINUTE)
        
        current_url = f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={app_id}"
        current_response = requests.get(current_url, timeout=10)
        current_players = 0
        
        if current_response.status_code == 200:
            data = current_response.json()
            current_players = data.get('response', {}).get('player_count', 0)
        
        return current_players
        
    except Exception as e:
        print(f"Error getting player count for {app_id}: {e}")
        return 0

def get_top_steam_games(force_refresh=False):
    """Get top Steam games using Steam's official API"""
    try:
        print("Fetching fresh data from Steam...")
        url = f"https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/?key={STEAM_API_KEY}"
        
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch data: {response.status_code}")
        
        data = response.json()
        ranks = data.get('response', {}).get('ranks', [])[:MAX_GAMES]
        
        if not ranks:
            raise Exception("No game data in API response")
        
        games_data = []
        print("\nFetching current player counts for games...")
        
        for rank, game in enumerate(ranks, 1):
            try:
                app_id = game.get('appid')
                game_name = game.get('name', '')
                
                if not game_name:
                    wait_for_rate_limit(store_call_times, STORE_CALLS_PER_MINUTE)
                    game_name = get_game_name(app_id)
                
                player_count = get_current_players(app_id)
                
                if player_count > 0:
                    games_data.append({
                        'Rank': rank,
                        'Game Name': game_name,
                        'Active Players': player_count
                    })
                    print(f"Game {rank}: {game_name}")
                    print(f"Current Players: {player_count:,}")
                    print("---")
                else:
                    print(f"Skipping {game_name} (no active players)")
            
            except Exception as e:
                print(f"Error processing game {rank}: {e}")
                continue
        
        if not games_data:
            raise Exception("No valid games data collected")
            
        df = pd.DataFrame(games_data)
        df = df.sort_values('Active Players', ascending=False).reset_index(drop=True)
        df['Rank'] = df.index + 1
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return df, timestamp
        
    except Exception as e:
        print(f"Error fetching fresh data: {e}")
        return None, None 