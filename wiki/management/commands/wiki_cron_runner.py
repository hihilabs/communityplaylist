"""
Daily scheduler for refresh_genre_wiki — runs at 03:00 local time.
Used by the wiki-cron Docker service (python:3.12-slim has no cron daemon).
"""
import time
import datetime
import subprocess
import sys

print('wiki-cron: started, runs refresh_genre_wiki daily at 03:00', flush=True)
while True:
    now = datetime.datetime.now()
    target = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    wait = (target - now).total_seconds()
    print(f'wiki-cron: next run in {wait/3600:.1f}h at {target}', flush=True)
    time.sleep(wait)
    print(f'wiki-cron: running refresh_genre_wiki at {datetime.datetime.now()}', flush=True)
    subprocess.run(
        [sys.executable, '/app/manage.py', 'refresh_genre_wiki',
         '--api-url', 'http://10.0.0.124:3001'],
        check=False,
    )
