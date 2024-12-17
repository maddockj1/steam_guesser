from flask import Flask, jsonify, render_template, request
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import pytz
from dotenv import load_dotenv
import time
from collections import deque

app = Flask(__name__)

CACHE_FILE = 'steam_cache.json'
CACHE_DURATION = timedelta(days=1)  # Cache data for 1 day
MOUNTAIN_TZ = pytz.timezone('America/Denver')

# Add your Steam API key here
STEAM_API_KEY = os.getenv('STEAM_API_KEY')

load_dotenv()

if not STEAM_API_KEY:
    raise ValueError("Steam API key not found in .env file")

# Rate limiting settings
CALLS_PER_MINUTE = 100  # Steam allows about 100 calls per minute
STORE_CALLS_PER_MINUTE = 10  # Store API has stricter limits
CALL_HISTORY_WINDOW = 60  # Window in seconds

# Rate limiting queues
api_call_times = deque(maxlen=CALLS_PER_MINUTE)
store_call_times = deque(maxlen=STORE_CALLS_PER_MINUTE)

# Add near other constants at top of file
MAX_GAMES = 50

def wait_for_rate_limit(call_times, calls_per_minute):
    """Implement rate limiting"""
    now = time.time()
    
    # Remove old timestamps
    while call_times and call_times[0] < now - CALL_HISTORY_WINDOW:
        call_times.popleft()
    
    # If we've hit the limit, wait
    if len(call_times) >= calls_per_minute:
        wait_time = call_times[0] - (now - CALL_HISTORY_WINDOW)
        if wait_time > 0:
            print(f"Rate limit reached, waiting {wait_time:.2f} seconds...")
            time.sleep(wait_time)
    
    # Add current timestamp
    call_times.append(now)

def should_update_cache():
    """Check if cache should be updated"""
    if not os.path.exists(CACHE_FILE):
        print("No cache file exists, will create new cache")
        return True
        
    try:
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
            cache_time = datetime.strptime(cache['timestamp'], "%Y-%m-%d %H:%M:%S")
            
        if datetime.now() - cache_time > CACHE_DURATION:
            print("Cache is older than 1 hour, will update")
            return True
            
        print(f"Cache is still valid, last updated: {cache['timestamp']}")
        return False
        
    except Exception as e:
        print(f"Error reading cache: {e}")
        return True

def get_cached_games():
    """Get games from cache file"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading cache: {e}")
    return None

def save_to_cache(df):
    """Save games data to cache file with validation"""
    try:
        # Validate data before saving
        if df.empty or 'Active Players' not in df.columns or df['Active Players'].sum() == 0:
            print("Warning: Attempting to cache invalid data")
            return
            
        cache_data = {
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'games': df.to_dict('records')
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f)
        print(f"Cache updated with {len(df)} valid games")
    except Exception as e:
        print(f"Error saving cache: {e}")

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
        
        # First get current players
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
    """Get top 10 Steam games using Steam's official API"""
    if not force_refresh and not should_update_cache():
        cached_data = get_cached_games()
        if cached_data:
            df = pd.DataFrame(cached_data['games'])
            if not df.empty and 'Active Players' in df.columns and df['Active Players'].sum() > 0:
                print("Using valid cached data from:", cached_data['timestamp'])
                return df, cached_data['timestamp']
            else:
                print("Cached data invalid or missing player counts, fetching fresh data...")
                force_refresh = True
    
    try:
        print("Fetching fresh data from Steam...")
        url = f"https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/?key={STEAM_API_KEY}"
        
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch data: {response.status_code}")
        
        data = response.json()
        # Limit to first 10 games
        ranks = data.get('response', {}).get('ranks', [])[:MAX_GAMES]
        
        if not ranks:
            raise Exception("No game data in API response")
        
        games_data = []
        print("\nFetching current player counts for top 10 games...")
        
        # Process games with proper rate limiting
        for rank, game in enumerate(ranks, 1):
            try:
                app_id = game.get('appid')
                game_name = game.get('name', '')
                
                # If no name in initial response, get it from store
                if not game_name:
                    wait_for_rate_limit(store_call_times, STORE_CALLS_PER_MINUTE)
                    game_name = get_game_name(app_id)
                
                # Get current player count
                player_count = get_current_players(app_id)
                
                if player_count > 0:  # Only add games with active players
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
            
        # Sort by player count and reassign ranks
        df = pd.DataFrame(games_data)
        df = df.sort_values('Active Players', ascending=False).reset_index(drop=True)
        df['Rank'] = df.index + 1
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_to_cache(df)
        print(f"\nSuccessfully cached {len(games_data)} games at {timestamp}")
        
        # Print final top 10 list
        print("\nFinal Top 10 Games by Current Players:")
        print("=====================================")
        for _, row in df.iterrows():
            print(f"{row['Rank']}. {row['Game Name']}: {row['Active Players']:,} players")
        
        return df, timestamp
        
    except Exception as e:
        print(f"Error fetching fresh data: {e}")
        cached_data = get_cached_games()
        if cached_data:
            df = pd.DataFrame(cached_data['games'])
            if not df.empty and 'Active Players' in df.columns and df['Active Players'].sum() > 0:
                print("Using valid cached data as fallback")
                return df, cached_data['timestamp']
        print("No valid data available")
        return None, None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/get-game-pair')
def get_game_pair():
    force_refresh = request.args.get('force', '').lower() == 'true'
    try:
        df, timestamp = get_top_steam_games(force_refresh)
        if df is not None and not df.empty:
            games = df.sample(n=1)
            return jsonify({
                'game': {
                    'name': games.iloc[0]['Game Name'],
                    'rank': int(games.iloc[0]['Rank']),
                    'players': int(games.iloc[0]['Active Players'])
                },
                'timestamp': timestamp,
                'cached': not force_refresh
            })
        return jsonify({'error': 'No games data available'})
    except Exception as e:
        print(f"Error in get_game_pair: {str(e)}")
        return jsonify({'error': f'Failed to fetch games data: {str(e)}'})

if __name__ == '__main__':
    app.run(debug=True) 