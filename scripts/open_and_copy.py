import webbrowser
import subprocess

url = 'http://localhost:3000/reset/InRlc3Qi.aX0S-w.3_fqFJN-f-e6mbzvMpsXmPUf4uc'
print('Opening:', url)
webbrowser.open(url)
# Copy to clipboard using PowerShell Set-Clipboard
subprocess.run(['powershell', '-NoProfile', '-Command', f"Set-Clipboard -Value '{url}'"], check=False)
print('Copied to clipboard')
