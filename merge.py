import os
import re

working_file = 'templates/index.html'
new_file = '../clarifi_ai_interactive_icons.html'

with open(working_file, 'r', encoding='utf-8') as f:
    old_content = f.read()

with open(new_file, 'r', encoding='utf-8') as f:
    new_content = f.read()

# 1. Grab the <head> and :root CSS from old_content
head_and_root_match = re.search(r'(<head>.*?:root\s*{.*?})\s*\*', old_content, re.DOTALL)
if not head_and_root_match:
    print("Could not find <head> and :root in old content")
    exit(1)
head_and_root = head_and_root_match.group(1)

# 2. Modify new_content body css to include the gradient
new_content = re.sub(
    r'body\s*{\s*font-family:\s*var\(--font-sans\);\s*background:\s*transparent;\s*}',
    '''body { 
    font-family: var(--font-sans); 
    background-color: var(--color-background-root);
    color: var(--color-text-primary);
    min-height: 100vh;
    background-image: 
      radial-gradient(circle at 15% 10%, rgba(124, 58, 237, 0.15), transparent 40%),
      radial-gradient(circle at 85% 30%, rgba(56, 189, 248, 0.1), transparent 40%),
      radial-gradient(circle at 50% 80%, rgba(236, 72, 153, 0.08), transparent 50%);
    background-attachment: fixed;
  }''',
    new_content
)

# 3. Inject IDs into the stats blocks so JS can update them
new_content = new_content.replace('<div class="stat-value">₹14,820</div>', '<div id="stat-total" class="stat-value">₹14,820</div>')
new_content = new_content.replace('<div class="stat-value">20</div>', '<div id="stat-tx" class="stat-value">20</div>')
new_content = new_content.replace('<div class="stat-value" style="font-size:17px;padding-top:3px;">Food & Dining</div>', '<div id="stat-top-cat" class="stat-value" style="font-size:17px;padding-top:3px;">Food & Dining</div>')
new_content = new_content.replace('<div class="stat-badge badge-warn">₹5,630 — 38%</div>', '<div id="stat-top-val" class="stat-badge badge-warn">₹5,630 — 38%</div>')
new_content = new_content.replace('<div class="stat-value">₹1,796</div>', '<div id="stat-sub-val" class="stat-value">₹1,796</div>')
new_content = new_content.replace('<div class="stat-badge badge-warn">4 active</div>', '<div id="stat-sub-count" class="stat-badge badge-warn">4 active</div>')

# 4. Expose charts to window
new_content = new_content.replace("new Chart(document.getElementById('donutChart'),", "window.donutChart = new Chart(document.getElementById('donutChart'),")
new_content = new_content.replace("new Chart(document.getElementById('lineChart'),", "window.lineChart = new Chart(document.getElementById('lineChart'),")

# 5. Extract our sendPrompt async function from old content
send_prompt_match = re.search(r'(async function sendPrompt\(defaultPrompt\).*?)\n\s*</script>', old_content, re.DOTALL)
if send_prompt_match:
    send_prompt_func = send_prompt_match.group(1)
    new_content = new_content.replace('</script>', '\n  ' + send_prompt_func + '\n</script>')

# Final assembly!
new_content_fixed = new_content.replace("<style>", "")
final_html = head_and_root.strip() + "\n" + new_content_fixed

with open(working_file, 'w', encoding='utf-8') as f:
    f.write(final_html)

print("Merge complete!")
