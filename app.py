from flask import Flask, jsonify, render_template, request
from datetime import datetime, timedelta
import json
import os
import pandas as pd
from api.steam_api import get_top_steam_games

app = Flask(__name__)

CACHE_FILE = 'steam_cache.json'
CACHE_DURATION = timedelta(days=1)

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
            print("Cache is older than 1 day, will update")
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
                cache_data = json.load(f)
                df = pd.DataFrame(cache_data['games'])
                return df, cache_data['timestamp']
    except Exception as e:
        print(f"Error loading cache: {e}")
    return None, None

def save_to_cache(df, timestamp):
    """Save games data to cache file"""
    try:
        if df.empty or 'Active Players' not in df.columns or df['Active Players'].sum() == 0:
            print("Warning: Attempting to cache invalid data")
            return
            
        cache_data = {
            'timestamp': timestamp,
            'games': df.to_dict('records')
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f)
        print(f"Cache updated with {len(df)} valid games")
    except Exception as e:
        print(f"Error saving cache: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/get-game-pair')
def get_game_pair():
    force_refresh = request.args.get('force', '').lower() == 'true'
    
    try:
        # Check cache first unless force refresh is requested
        if not force_refresh and not should_update_cache():
            df, timestamp = get_cached_games()
            if df is not None:
                print("Using cached data")
        else:
            # Only make API call if cache is invalid or force refresh
            df, timestamp = get_top_steam_games(force_refresh)
            if df is not None:
                save_to_cache(df, timestamp)
        
        if df is None or df.empty:
            return jsonify({
                'error': 'No games data available',
                'status': 'error'
            }), 500
            
        games = df.sample(n=1)
        return jsonify({
            'status': 'success',
            'game': {
                'name': games.iloc[0]['Game Name'],
                'rank': int(games.iloc[0]['Rank']),
                'players': int(games.iloc[0]['Active Players'])
            },
            'timestamp': timestamp,
            'cached': not force_refresh
        })
        
    except Exception as e:
        print(f"Error in get_game_pair: {str(e)}")
        return jsonify({
            'error': f'Failed to fetch games data: {str(e)}',
            'status': 'error'
        }), 500

if __name__ == '__main__':
    app.run(debug=True) 