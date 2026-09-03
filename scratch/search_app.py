import re

content = open('frontend/static/js/app.js', encoding='utf-8').read()
calls = re.findall(r'authFetch\s*\(\s*[`\'"]([^`\'"]+)[`\'"]', content)
print(f"Total authFetch string calls: {len(calls)}")
for c in sorted(set(calls)):
    print(" ", c)

dyn_calls = re.findall(r'authFetch\s*\(\s*`([^`]+)`', content)
print(f"\nTotal authFetch template literal calls: {len(dyn_calls)}")
for c in sorted(set(dyn_calls)):
    print(" ", c)
