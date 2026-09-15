import asyncio
import json
import subprocess
import time
import urllib.request
import websockets

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9222
UI_URL = "http://192.168.139.2:5055/"

async def send_cdp(ws, method, params=None, msg_id=[1]):
    mid = msg_id[0]
    msg_id[0] += 1
    payload = {"id": mid, "method": method, "params": params or {}}
    await ws.send(json.dumps(payload))
    while True:
        resp = await ws.recv()
        data = json.loads(resp)
        if data.get("id") == mid:
            return data.get("result", {})

async def eval_js(ws, expr):
    res = await send_cdp(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
    val = res.get("result", {}).get("value")
    return val

async def capture_screenshot(ws, out_path):
    res = await send_cdp(ws, "Page.captureScreenshot", {"format": "png"})
    data = res.get("data")
    if data:
        import base64
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(data))
        print(f"📸 Saved screenshot: {out_path}")

async def main():
    import tempfile, shutil
    temp_dir = tempfile.mkdtemp(prefix="chrome_e2e_")
    print("🚀 Launching Headless Chrome on port", PORT, "with profile", temp_dir, flush=True)
    chrome_proc = subprocess.Popen([
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={temp_dir}",
        "--window-size=1280,850",
        "--disable-gpu",
        "--no-first-run",
        "about:blank"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        # Wait for CDP to be available
        for _ in range(20):
            try:
                with urllib.request.urlopen(f"http://localhost:{PORT}/json") as r:
                    pages = json.loads(r.read())
                    if pages:
                        break
            except Exception:
                time.sleep(0.3)
        else:
            raise RuntimeError("Failed to connect to Chrome remote debugging port")

        ws_url = pages[0]["webSocketDebuggerUrl"]
        print(f"🔗 Connected to CDP at {ws_url}", flush=True)

        async with websockets.connect(ws_url, max_size=25_000_000) as ws:
            await send_cdp(ws, "Page.enable")
            await send_cdp(ws, "Runtime.enable")

            # Navigate to Holmes UI
            print(f"🌐 Navigating to {UI_URL}...")
            await send_cdp(ws, "Page.navigate", {"url": UI_URL})

            # Wait 3 seconds for initial status & models fetch
            await asyncio.sleep(3)

            # Test 1: System status
            status_text = await eval_js(ws, "document.getElementById('status-text') ? document.getElementById('status-text').textContent.trim() : ''")
            print(f"✅ Status Text: '{status_text}'")
            assert "Connected" in status_text, f"Expected Connected, got {status_text}"

            # Test 2: Verify dynamic backend models optgroup populated
            optgroup_count = await eval_js(ws, "document.getElementById('backend-models-optgroup').children.length")
            print(f"✅ Backend Models in dropdown optgroup count: {optgroup_count}")
            assert optgroup_count > 0, "Backend models optgroup is empty!"

            optgroup_values = await eval_js(ws, "Array.from(document.getElementById('backend-models-optgroup').children).map(o => o.value)")
            print(f"✅ Optgroup values: {optgroup_values}")

            # Test 3: Verify modal backend model chips rendered
            chip_count = await eval_js(ws, "document.querySelectorAll('#backend-models-chips .model-chip').length")
            badge_text = await eval_js(ws, "document.getElementById('backend-models-count') ? document.getElementById('backend-models-count').textContent.trim() : ''")
            print(f"✅ Backend Models Chips in Modal: {chip_count} (Badge: '{badge_text}')")
            assert chip_count == 12, f"Expected 12 chips, got {chip_count}"

            # Test 4: Open Custom Model Modal via dropdown selection
            print("🖱️ Selecting '+ Custom Model...' in dropdown...")
            await eval_js(ws, """
                const sel = document.getElementById('model-select');
                sel.value = 'custom';
                sel.dispatchEvent(new Event('change'));
            """)
            await asyncio.sleep(0.5)

            is_modal_visible = await eval_js(ws, "window.getComputedStyle(document.getElementById('custom-model-modal')).display === 'flex'")
            print(f"✅ Custom Model Modal visible: {is_modal_visible}")
            assert is_modal_visible, "Custom model modal did not open!"

            # Test 5: Click a specific model chip ('gemini/gemini-3.8-flash')
            target_model = "gemini/gemini-3.8-flash"
            print(f"🖱️ Clicking chip for '{target_model}'...")
            await eval_js(ws, f"""
                const chips = Array.from(document.querySelectorAll('#backend-models-chips .model-chip'));
                const targetChip = chips.find(c => c.textContent.includes('{target_model}'));
                if (targetChip) targetChip.click();
            """)
            await asyncio.sleep(0.3)

            input_val = await eval_js(ws, "document.getElementById('custom-model-input').value")
            print(f"✅ Input field populated with: '{input_val}'")
            assert input_val == target_model, f"Expected {target_model}, got {input_val}"

            # Test 6: Click 'Apply Model' button
            print("🖱️ Clicking 'Apply Model' button...")
            await eval_js(ws, "document.getElementById('save-modal-btn').click()")
            await asyncio.sleep(0.8)

            # Test 7: Verify modal is closed, active selection updated, localStorage updated
            is_modal_closed = await eval_js(ws, "window.getComputedStyle(document.getElementById('custom-model-modal')).display === 'none'")
            selected_model_dropdown = await eval_js(ws, "document.getElementById('model-select').value")
            ls_model = await eval_js(ws, "localStorage.getItem('holmes_selected_model')")
            active_indicator = await eval_js(ws, "document.getElementById('active-model-indicator') ? document.getElementById('active-model-indicator').textContent.trim() : ''")

            print(f"✅ Modal closed: {is_modal_closed}")
            print(f"✅ Dropdown active value: '{selected_model_dropdown}'")
            print(f"✅ LocalStorage value: '{ls_model}'")
            print(f"✅ Active Model Indicator: '{active_indicator}'")

            assert is_modal_closed, "Modal should be closed after Apply"
            assert selected_model_dropdown == target_model, f"Expected {target_model}, got {selected_model_dropdown}"
            assert ls_model == target_model, f"Expected {target_model} in localStorage, got {ls_model}"
            assert "Gemini 3.8 Flash" in active_indicator, f"Active indicator missing expected name: {active_indicator}"

            print("\n🎉 ALL E2E BROWSER TESTS PASSED SUCCESSFULLY!")

    finally:
        chrome_proc.terminate()
        chrome_proc.wait()

if __name__ == "__main__":
    asyncio.run(main())
