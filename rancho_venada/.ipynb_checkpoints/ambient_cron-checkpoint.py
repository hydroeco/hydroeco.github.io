import os
import datetime
import pandas as pd
import json
import time
from urllib.request import urlopen

def main():
    # --- CONFIGURATION ---
    # 1. Start exactly where your data picks up in 2025
    START_DATE = datetime.datetime(2025, 8, 10, 4, 0) 
    
    # 2. Stop when we reach the old 2024 data
    STOP_DATE = datetime.datetime(2024, 11, 21, 2, 0)
    
    FILE_PATH = '/home/daviddralle/hydroeco.github.io/rancho_venada/rv_ambient.csv'
    API_KEY = '151c39a65f204f31b26e4c878003137608e974e6c811436cb010bc22ff68c5eb'
    APP_KEY = '6039741f988f4b76964cbd2b5cf2378a796807cdcda14b6288cf399c6000d9bd'
    MAC = 'C4:5B:BE:5E:07:90'

    print(f"--- GAP FILLER MODE ---")
    print(f"Start Point: {START_DATE}")
    print(f"Goal:        {STOP_DATE}")
    print(f"Strategy:    Download backwards. If empty, jump back 24h and retry.")
    print("-----------------------")

    current_end_date = START_DATE
    new_data_frames = []
    gap_counter = 0
    
    while True:
        # Success Check
        if current_end_date <= STOP_DATE:
            print("\nSUCCESS: Target date reached!")
            break

        end_str = current_end_date.strftime('%Y-%m-%dT%H:%M')
        url = f'https://rt.ambientweather.net/v1/devices/{MAC}?apiKey={API_KEY}&applicationKey={APP_KEY}&endDate={end_str}&limit=288'
        
        try:
            response = urlopen(url)
            data_json = json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"Error: {e}. Retrying...")
            time.sleep(5)
            continue

        # --- GAP JUMPING LOGIC ---
        if not data_json:
            gap_counter += 1
            print(f"   [No Data] Ending {end_str}. Jumping back 1 day (Jump #{gap_counter})...")
            current_end_date = current_end_date - datetime.timedelta(days=1)
            time.sleep(0.5)
            continue
        
        # Reset counter if we found data
        gap_counter = 0

        # Process Data
        df = pd.DataFrame.from_dict(data_json)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        
        # Timezone Conversion
        df.index = df.index.tz_convert('US/Pacific').tz_localize(None)
        
        new_data_frames.append(df)
        
        min_date = df.index.min()
        print(f"Fetched {len(df)} pts. Reached: {min_date}")
        
        current_end_date = min_date
        time.sleep(1.1)

    # Save logic
    if new_data_frames:
        print("Merging and saving...")
        new_chunk = pd.concat(new_data_frames)
        
        if os.path.exists(FILE_PATH):
            # Load original, forcing datetime index to fix format mismatches
            rv_ambient = pd.read_csv(FILE_PATH, index_col=0)
            rv_ambient.index = pd.to_datetime(rv_ambient.index, utc=False)
            
            combined = pd.concat([rv_ambient, new_chunk])
        else:
            combined = new_chunk
            
        # Clean up
        combined = combined[~combined.index.duplicated(keep='first')]
        combined = combined.sort_index()
        
        combined.to_csv(FILE_PATH)
        print("Done.")
    else:
        print("No new data downloaded.")

if __name__ == '__main__':
    main()