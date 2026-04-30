# pass

| In Use | Still Fixing |
|--------|--------------|
| ❌     | ❌           |

Interactive CLI wrapper around GnuPG and the standard Unix password manager (pass). Walks the user through selecting or creating a GPG key, initializing the password store, and storing a new password - all in a guided, colorized terminal flow.

## pass.py

### Workflow

1. Checks that gpg and pass are installed.
2. Lists existing GPG secret keys and lets the user pick one, or generates a new 4096-bit RSA key pair.
3. Initializes `~/.password-store` with the chosen key if needed.
4. Prompts for a password name and value, confirms, and stores it via `pass insert`.

### Requirements

- gnupg (gpg)
- pass (https://www.passwordstore.org)

### Usage

```bash
python3 pass.py
```
