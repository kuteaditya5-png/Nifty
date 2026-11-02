"""Optional continuous collector: python monitor_worker.py (site must be running).
Use a service supervisor on an always-on host; do not run inside a Vercel request.
"""
import os
import time
import requests
from dotenv import load_dotenv

def run():
    load_dotenv()
    url=os.environ['NIFTY_SITE_URL'].rstrip('/')+'/api/signal-journal/collect'
    secret=os.environ['NIFTY_MONITOR_SECRET']
    while True:
        try:
            response=requests.post(url,headers={'X-Monitor-Secret':secret},timeout=180)
            response.raise_for_status()
            print(response.json(),flush=True)
        except Exception as exc:
            print('Collection failed:',type(exc).__name__,flush=True)
        time.sleep(30)

if __name__=='__main__':run()
