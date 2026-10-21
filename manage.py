"""Combah administration CLI: create the initial administrator or reset a staff password.
Usage: python manage.py create-admin | python manage.py reset-password
Passwords are entered securely through the terminal (not command-line arguments).
"""
import getpass, sqlite3
from app import db, now, hash_password, insert_user, seed_demo

def create_admin():
    print('Create the first Combah administrator')
    name=input('Full name: ').strip()
    email=input('Email: ').strip().lower()
    if not name or '@' not in email:raise SystemExit('Name and email are required.')
    password=getpass.getpass('Password (12+ characters): ')
    confirm=getpass.getpass('Confirm password: ')
    if len(password)<12 or password!=confirm:raise SystemExit('Use a matching password with at least 12 characters.')
    with db() as c:
        try:
            uid=insert_user(c,name,email,password,'admin')
        except sqlite3.IntegrityError:raise SystemExit('Email already exists.')
    print(f'Admin account #{uid} created. No password has been printed.')

def seed_demo_data():
    with db() as c:
        if c.execute("SELECT id FROM users WHERE email='admin@combah.demo'").fetchone():
            print('Demo data already present; no changes made.')
            return
        seed_demo(c)
    print('Demo accounts and sample records created:')
    print('  customer@combah.demo / DemoPass!2026')
    print('  warehouse@combah.demo / DemoPass!2026')
    print('  admin@combah.demo / DemoPass!2026')



def reset_password():
    email=input('Email of existing account: ').strip().lower()
    pw=getpass.getpass('New password (12+ characters): ')
    if len(pw)<12:raise SystemExit('Password is too short.')
    confirm=getpass.getpass('Confirm password: ')
    if pw!=confirm:raise SystemExit('Passwords do not match.')
    with db() as c:
        cur=c.execute('UPDATE users SET password=? WHERE email=?',(hash_password(pw),email))
        if cur.rowcount!=1:raise SystemExit('Account not found.')
        uid=c.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()['id']
        c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
    print('Password changed; existing sessions revoked.')

if __name__=='__main__':
    import sys
    cmd=sys.argv[1] if len(sys.argv)>1 else None
    {'create-admin':create_admin,'seed-demo':seed_demo_data,'reset-password':reset_password}.get(cmd,lambda:print('Usage: python manage.py create-admin | python manage.py seed-demo | python manage.py reset-password'))()
