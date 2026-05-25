"""
Daily scheduler — runs at configured times each day.
Used by the wiki-cron Docker service (python:3.12-slim has no cron daemon).

Schedule:
  03:00 — refresh_genre_wiki    (lightweight edge-weight refresh)
  14:00 — blast_verified_profiles  (drip one promoter profile to social)
"""
import time
import datetime
import subprocess
import sys

JOBS = [
    {'hour': 3,  'cmd': ['refresh_genre_wiki', '--api-url', 'http://10.0.0.124:3001']},
    {'hour': 14, 'cmd': ['blast_verified_profiles']},
]

print('wiki-cron: started', flush=True)
for job in JOBS:
    print(f"  {job['hour']:02d}:00 → {' '.join(job['cmd'])}", flush=True)


def next_run(hour):
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


while True:
    now = datetime.datetime.now()
    # Find the nearest upcoming job
    upcoming = [(next_run(j['hour']), j) for j in JOBS]
    upcoming.sort(key=lambda x: x[0])
    next_time, next_job = upcoming[0]

    wait = (next_time - now).total_seconds()
    print(f"wiki-cron: sleeping {wait/3600:.1f}h → {next_job['cmd'][0]} at {next_time}", flush=True)
    time.sleep(wait)

    print(f"wiki-cron: running {next_job['cmd'][0]} at {datetime.datetime.now()}", flush=True)
    subprocess.run([sys.executable, '/app/manage.py'] + next_job['cmd'], check=False)
