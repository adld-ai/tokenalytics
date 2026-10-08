import subprocess, sys, time, os
from playwright.sync_api import sync_playwright
root=os.path.abspath(os.path.join(os.path.dirname(__file__),'..','..'))
srv=subprocess.Popen([sys.executable,'-m','http.server','8765','--bind','127.0.0.1'],cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
time.sleep(1)
try:
    with sync_playwright() as p:
        b=p.chromium.launch(); pg=b.new_page(viewport={'width':1280,'height':720})
        errs=[]; pg.on('console',lambda m: errs.append(m.text) if m.type=='error' else None); pg.on('pageerror',lambda e: errs.append(str(e)))
        pg.goto('http://127.0.0.1:8765/classroom/index.html?src=/classroom/fixtures/status.sample.json'); pg.wait_for_selector('.tile'); time.sleep(0.5)
        n=pg.locator('.tile').count(); sh=pg.evaluate('document.documentElement.scrollHeight'); first=pg.locator('.tile').first.get_attribute('data-sev')
        who=pg.locator('.tile .who').first.inner_text()
        pg.screenshot(path=os.path.join(os.path.dirname(__file__),'screenshot.png'))
        pg.goto('http://127.0.0.1:8765/classroom/index.html?src=/classroom/fixtures/status.sample.json&unmask=1'); pg.wait_for_selector('.tile'); who2=pg.locator('.tile .who').first.inner_text()
        pg.goto('http://127.0.0.1:8765/classroom/index.html?src=/nope.json'); time.sleep(0.8); err=pg.locator('#err').inner_text()
        b.close()
    print({'tiles':n,'scrollHeight':sh,'first_sev':first,'masked':'***' in who,'unmasked_has_full':'trainee' in who2,'console_errors':errs,'missing_src_msg':err})
finally: srv.terminate()
