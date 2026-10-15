"""Check a proposed source-only public checkout. Never print matched values."""
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', 'node_modules', '.venv', 'venv', 'dist', 'build', '__pycache__', '.pytest_cache'}
BLOCK_DIRS = {'backups', 'backup', 'secrets', 'credentials', 'logs', 'data', 'cache'}
PATTERNS = {
    'telegram-token': re.compile(r'\b\d{6,14}:[A-Za-z0-9_-]{30,}\b'),
    'private-key': re.compile(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----'),
    'proxy-credential-uri': re.compile(r'\b(?:ss|ssr|vmess|vless|trojan|anytls)://\S+', re.I),
    'url-userinfo': re.compile(r'https?://[^\s/]+:[^\s/@]+@', re.I),
    'url-query-credential': re.compile(r'https?://[^\s\x22\x27]+[?&](?:token|key|auth|secret|password)=[^\s\x22\x27&]+', re.I),
}
ASSIGNMENT = re.compile(r"""(?ix)
(?:\b(?:[A-Z_]*(?:TOKEN|PASSWORD|SECRET|CHAT_ID|API_KEY)[A-Z_]*)|
[\x22\x27](?:token|password|secret|chat_id|api_key)[\x22\x27])
\s*[:=]\s*[\x22\x27]([^\x22\x27\r\n]+)[\x22\x27]
""")
PLACEHOLDERS = {'replace-me', 'change-me', 'set_locally', 'your_token', 'your_chat_id'}

def forbidden(relative):
    parts = [part.lower() for part in relative.parts]
    name = parts[-1]
    if any(part in BLOCK_DIRS for part in parts[:-1]):
        return True
    if name.endswith('.example') or '.example.' in name:
        return False
    if name == '.env' or name.startswith('.env.') or name.endswith('.env'):
        return True
    if re.search(r'\.(?:db|sqlite|sqlite3)(?:$|-)|\.(?:bak|old|orig|pem|key|p12|pfx|log|zip|gz|tgz|7z)(?:$|\.)', name):
        return True
    return (name in {'config.yaml', 'config.yml', 'nodes.yaml', 'config.json', 'secrets.json', 'credentials.json'}
            or relative.as_posix() == 'backend/probe-settings.json')

def paths():
    found = set()
    for directory, subdirs, files in os.walk(ROOT):
        subdirs[:] = [name for name in subdirs if name not in SKIP]
        for name in files:
            found.add((Path(directory) / name).relative_to(ROOT))
    # A previously tracked file cannot be hidden merely by adding .gitignore.
    if (ROOT / '.git').exists():
        result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-z'], capture_output=True)
        if result.returncode:
            raise RuntimeError('Cannot inspect the Git index')
        found.update(Path(name) for name in result.stdout.decode().split('\0') if name)
    return sorted(found)

def main():
    failures = []
    for relative in paths():
        if forbidden(relative) or any(part in SKIP for part in relative.parts):
            failures.append((relative, 0, 'forbidden-publish-path'))
            continue
        file = ROOT / relative
        if file.is_symlink():
            failures.append((relative, 0, 'symlink-needs-review'))
            continue
        if not file.is_file():
            continue
        try:
            content = file.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            failures.append((relative, 0, 'binary-needs-visual-review'))
            continue
        for number, line in enumerate(content.splitlines(), 1):
            for kind, pattern in PATTERNS.items():
                if pattern.search(line):
                    failures.append((relative, number, kind))
            for match in ASSIGNMENT.finditer(line):
                if match.group(1).lower() not in PLACEHOLDERS:
                    failures.append((relative, number, 'possible-literal-credential'))
    for relative, line, kind in failures:
        print(f'{relative.as_posix()}:{line}: {kind}')
    if failures:
        print(f'FAIL: {len(failures)} findings. Matched values are intentionally hidden.')
        return 1
    print('PASS: source-only tree and basic secret patterns. Manual review is still required.')
    return 0

if __name__ == '__main__':
    sys.exit(main())
