"""Combah Procurement & Logistics MVP. Python 3.10+ / FastAPI / SQLite.

Local/demo-first, no live payments or warehouse address until owner supplies details.
"""
import os, sqlite3, secrets, hashlib, hmac, json, time, re
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('COMBAH_DATA_DIR', str(ROOT / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / 'combah.sqlite3'
DEMO = os.getenv('COMBAH_DEMO', '0') == '1'
SECURE_COOKIES = os.getenv('COMBAH_SECURE_COOKIES', '0') == '1'
COOKIE_NAME = 'combah_sid'
REGIONS = ['Ahafo','Ashanti','Bono','Bono East','Central','Eastern','Greater Accra','North East','Northern','Oti','Savannah','Upper East','Upper West','Volta','Western','Western North']
ORDER_STATES = ['AWAITING_PAYMENT','PAYMENT_REVIEW','OFFICER_REVIEW','PROCUREMENT','SUPPLIER_DISPATCH','RECEIVED_IN_CHINA','READY_FOR_SHIPPING','IN_TRANSIT','ARRIVED_GHANA','CLEARANCE','DISPATCHED_TO_REGION','READY_FOR_COLLECTION','COMPLETED']
SHIP_STATES = ['READY_FOR_SHIPPING','IN_TRANSIT','ARRIVED_GHANA','CLEARANCE','DISPATCHED_TO_REGION','READY_FOR_COLLECTION','COMPLETED']
PACKAGE_STATES = ['RECEIVED_IN_CHINA','READY_FOR_SHIPPING','IN_TRANSIT','ARRIVED_GHANA','CLEARANCE','DISPATCHED_TO_REGION','READY_FOR_COLLECTION','COMPLETED']

app = FastAPI(title='Combah Procurement & Logistics API', version='1.1.0', docs_url='/api/docs', redoc_url=None)

@app.middleware('http')
async def security_headers(request:Request, call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='private, no-store'
    if SECURE_COOKIES:
        response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    return response


@contextmanager
def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def row(r): return dict(r) if r else None
def rows(rs): return [dict(r) for r in rs]
def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 350000)
    return 'pbkdf2_sha256$350000$'+salt.hex()+'$'+digest.hex()
def check_password(password, stored):
    try:
        alg, rounds, s, p = stored.split('$')
        if alg != 'pbkdf2_sha256': return False
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(s), int(rounds))
        return hmac.compare_digest(digest, bytes.fromhex(p))
    except (ValueError, AttributeError): return False

def initdb():
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT UNIQUE, full_name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE COLLATE NOCASE, phone TEXT DEFAULT '', password TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('customer','warehouse','admin')),
          region TEXT DEFAULT '', district TEXT DEFAULT '', address TEXT DEFAULT '',
          created_at TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          csrf TEXT NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT, order_ref TEXT UNIQUE, customer_id INTEGER NOT NULL REFERENCES users(id),
          product_url TEXT NOT NULL, product_name TEXT NOT NULL, unit_price_cents INTEGER NOT NULL,
          quantity INTEGER NOT NULL, estimated_weight REAL, region TEXT NOT NULL,
          district TEXT DEFAULT '', delivery_type TEXT NOT NULL DEFAULT 'pickup', notes TEXT DEFAULT '',
          procurement_fee_cents INTEGER NOT NULL, handling_fee_cents INTEGER NOT NULL,
          freight_estimate_cents INTEGER NOT NULL, total_cents INTEGER NOT NULL,
          quote_note TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'AWAITING_PAYMENT',
          supplier_tracking TEXT DEFAULT '', staff_note TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS payments (
          id INTEGER PRIMARY KEY AUTOINCREMENT, payment_ref TEXT UNIQUE, order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
          amount_cents INTEGER NOT NULL, method TEXT NOT NULL DEFAULT 'manual', customer_reference TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'AWAITING_REFERENCE', reviewed_by INTEGER REFERENCES users(id),
          reviewed_at TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS packages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, package_ref TEXT UNIQUE, customer_id INTEGER NOT NULL REFERENCES users(id),
          order_id INTEGER REFERENCES orders(id), supplier TEXT DEFAULT '', tracking_number TEXT DEFAULT '',
          description TEXT DEFAULT '', weight_kg REAL, length_cm REAL, width_cm REAL, height_cm REAL,
          count INTEGER NOT NULL DEFAULT 1, damaged INTEGER NOT NULL DEFAULT 0, notes TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'RECEIVED_IN_CHINA',
          received_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ship_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          request_ref TEXT UNIQUE,
          customer_id INTEGER NOT NULL REFERENCES users(id),
          product_name TEXT NOT NULL,
          supplier TEXT DEFAULT '', supplier_tracking TEXT DEFAULT '',
          estimated_weight REAL, quantity INTEGER NOT NULL DEFAULT 1,
          region TEXT NOT NULL, district TEXT DEFAULT '', delivery_type TEXT NOT NULL DEFAULT 'pickup',
          notes TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'PRE_REGISTERED',
          matched_package_id INTEGER REFERENCES packages(id),
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_shipreq_customer ON ship_requests(customer_id);
        CREATE TABLE IF NOT EXISTS shipments (
          id INTEGER PRIMARY KEY AUTOINCREMENT, shipment_ref TEXT UNIQUE, carrier TEXT DEFAULT '', tracking_number TEXT DEFAULT '',
          destination_region TEXT NOT NULL, eta TEXT DEFAULT '', notes TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'READY_FOR_SHIPPING', created_by INTEGER REFERENCES users(id),
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS shipment_packages (
          shipment_id INTEGER NOT NULL REFERENCES shipments(id), package_id INTEGER NOT NULL UNIQUE REFERENCES packages(id),
          PRIMARY KEY(shipment_id, package_id));
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL,
          actor_id INTEGER REFERENCES users(id), event TEXT NOT NULL, detail TEXT DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
          title TEXT NOT NULL, message TEXT NOT NULL, read_at TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_orders_customer ON orders(customer_id);
        CREATE INDEX IF NOT EXISTS ix_packages_customer ON packages(customer_id);
        CREATE INDEX IF NOT EXISTS ix_events_entity ON events(entity_type,entity_id);
        CREATE INDEX IF NOT EXISTS ix_notifications_user ON notifications(user_id);
        ''')
        defaults = {'procurement_percent':'7.5', 'handling_fee_ghs':'35', 'estimated_freight_per_kg_ghs':'50',
                    'ship_for_me_handling_ghs':'0', 'currency':'GHS', 'support_email':'', 'support_phone':'', 'china_warehouse_address':'',
                    'ghana_hub':'Tamale, Northern Region, Ghana', 'notice':'Shipping is estimated until packages are weighed in China.'}
        for k,v in defaults.items(): c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)',(k,v))
        if DEMO and not c.execute('SELECT id FROM users WHERE email=?',('admin@combah.demo',)).fetchone():
            seed_demo(c)

def insert_user(c, name, email, pw, role, region='', phone='', district=''):
    c.execute('INSERT INTO users(full_name,email,phone,password,role,region,district,created_at) VALUES(?,?,?,?,?,?,?,?)',
              (name,email,phone,hash_password(pw),role,region,district,now()))
    uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    if role=='customer': c.execute('UPDATE users SET customer_id=? WHERE id=?',(f'CMB-GH-{uid:06d}',uid))
    return uid

def event(c, typ, eid, actor, action, detail=''):
    c.execute('INSERT INTO events(entity_type,entity_id,actor_id,event,detail,created_at) VALUES(?,?,?,?,?,?)',
              (typ,eid,actor,action,detail,now()))

def notify(c, uid, title, message):
    c.execute('INSERT INTO notifications(user_id,title,message,created_at) VALUES(?,?,?,?)',(uid,title,message,now()))

def seed_demo(c):
    admin=insert_user(c,'Combah Operations','admin@combah.demo','DemoPass!2026','admin','Northern')
    wh=insert_user(c,'China Warehouse Team','warehouse@combah.demo','DemoPass!2026','warehouse')
    u=insert_user(c,'Ama Mensah','customer@combah.demo','DemoPass!2026','customer','Greater Accra','0240000000','Accra')
    insert_user(c,'Kwame Owusu','kwame@combah.demo','DemoPass!2026','customer','Northern')
    t=now()
    for ref,desc,unit,qty,fee,handling,freight,total,state in [
      ('CMB-ORD-000001','Wireless headphones',45000,2,6750,3500,5000,105250,'PROCUREMENT'),
      ('CMB-ORD-000002','LED desk lamp',18000,1,1350,3500,2500,25350,'AWAITING_PAYMENT'),
    ]:
        c.execute('''INSERT INTO orders(order_ref,customer_id,product_url,product_name,unit_price_cents,quantity,
            estimated_weight,region,district,delivery_type,procurement_fee_cents,handling_fee_cents,
            freight_estimate_cents,total_cents,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (ref,u,'https://example.com/sample-product',desc,unit,qty,1,'Greater Accra','Accra','pickup',fee,handling,freight,total,state,t,t))
        oid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        pstate='VERIFIED' if state=='PROCUREMENT' else 'AWAITING_REFERENCE'
        c.execute('INSERT INTO payments(payment_ref,order_id,amount_cents,status,created_at) VALUES(?,?,?,?,?)',
                  (f'CMB-PAY-{oid:06d}',oid,total,pstate,t))
        event(c,'order',oid,admin,'ORDER_CREATED','Sample order for preview')
    c.execute('''INSERT INTO packages(package_ref,customer_id,supplier,tracking_number,description,weight_kg,count,status,received_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)''',('CMB-PKG-000001',u,'Demo supplier','CN83920175','Accessories and small electronics',2.4,1,'IN_TRANSIT',wh,t,t))
    pid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute('''INSERT INTO shipments(shipment_ref,carrier,tracking_number,destination_region,status,created_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?)''',('CMB-SHP-000001','Consolidated air freight','CB-AIR-1092','Greater Accra','IN_TRANSIT',admin,t,t))
    sid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute('INSERT INTO shipment_packages VALUES(?,?)',(sid,pid))
    event(c,'package',pid,wh,'RECEIVED_IN_CHINA','Sample package for preview')
    event(c,'shipment',sid,admin,'IN_TRANSIT','Sample air shipment')
    notify(c,u,'Your parcel is on the move','Sample parcel CMB-PKG-000001 is in transit to Ghana.')

initdb()

class Signup(BaseModel):
    full_name: str=Field(min_length=2,max_length=120)
    email: str=Field(min_length=5,max_length=180)
    password: str=Field(min_length=10,max_length=160)
    phone: str=Field(default='',max_length=30)
    region: str
    district: str=Field(default='',max_length=80)
class Login(BaseModel):
    email: str
    password: str
class Profile(BaseModel):
    full_name:str=Field(min_length=2,max_length=120)
    phone:str=Field(default='',max_length=30)
    region:str=''
    district:str=Field(default='',max_length=80)
    address:str=Field(default='',max_length=200)
class OrderIn(BaseModel):
    product_url:str=Field(min_length=8,max_length=1500)
    product_name:str=Field(min_length=2,max_length=200)
    unit_price:Decimal=Field(gt=0,lt=100000000)
    quantity:int=Field(ge=1,le=10000)
    estimated_weight:Optional[float]=Field(default=None,gt=0,le=100000)
    region:str
    district:str=Field(default='',max_length=80)
    delivery_type:str='pickup'
    notes:str=Field(default='',max_length=1000)
class PaymentRef(BaseModel):
    reference:str=Field(min_length=3,max_length=120)
    method:str=Field(default='bank_transfer',max_length=40)
class ShipRequestIn(BaseModel):
    product_name:str=Field(min_length=2,max_length=200)
    supplier:str=Field(default='',max_length=150)
    supplier_tracking:str=Field(default='',max_length=150)
    estimated_weight:Optional[float]=Field(default=None,gt=0,le=100000)
    quantity:int=Field(default=1,ge=1,le=10000)
    region:str
    district:str=Field(default='',max_length=80)
    delivery_type:str='pickup'
    notes:str=Field(default='',max_length=1000)

class PkgIn(BaseModel):
    customer_id:str
    ship_request_ref:str=''
    order_ref:str=''
    supplier:str=Field(default='',max_length=150)
    tracking_number:str=Field(default='',max_length=150)
    description:str=Field(default='',max_length=400)
    weight_kg:Optional[float]=Field(default=None,gt=0,le=100000)
    length_cm:Optional[float]=Field(default=None,gt=0,le=10000)
    width_cm:Optional[float]=Field(default=None,gt=0,le=10000)
    height_cm:Optional[float]=Field(default=None,gt=0,le=10000)
    count:int=Field(default=1,ge=1,le=10000)
    damaged:bool=False
    notes:str=Field(default='',max_length=1000)
class PkgUpdate(BaseModel):
    status:str
    notes:str=Field(default='',max_length=1000)
    damaged:Optional[bool]=None
class ShipIn(BaseModel):
    package_ids:list[int]=Field(min_length=1,max_length=100)
    carrier:str=Field(default='',max_length=120)
    tracking_number:str=Field(default='',max_length=150)
    destination_region:str
    eta:str=Field(default='',max_length=80)
    notes:str=Field(default='',max_length=400)
class ShipUpdate(BaseModel):
    status:str
    carrier:Optional[str]=Field(default=None,max_length=120)
    tracking_number:Optional[str]=None
    eta:Optional[str]=None
    notes:Optional[str]=None
class PaymentDecision(BaseModel):
    approved:bool
    note:str=Field(default='',max_length=400)
class OrderUpdate(BaseModel):
    status:str
    supplier_tracking:Optional[str]=None
    staff_note:Optional[str]=None
class StaffIn(BaseModel):
    full_name:str=Field(min_length=2,max_length=120)
    email:str
    password:str=Field(min_length=12,max_length=160)
    role:str

_attempts={}
def limited(key, limit=12, within=900):
    ts=time.time(); a=[x for x in _attempts.get(key,[]) if ts-x<within]
    if len(a)>=limit: raise HTTPException(429,'Too many attempts. Try again later.')
    a.append(ts); _attempts[key]=a

def user_public(u):
    return {k:u[k] for k in ('id','customer_id','full_name','email','phone','role','region','district','address','created_at')}

def current_user(request:Request):
    raw=request.cookies.get(COOKIE_NAME)
    if not raw:return None
    with db() as c:
        result=c.execute('''SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id
          WHERE s.token_hash=? AND s.expires>? AND u.is_active=1''',(hashlib.sha256(raw.encode()).hexdigest(),int(time.time()))).fetchone()
        return dict(result) if result else None

def require(*roles):
    def inner(request:Request):
        u=current_user(request)
        if not u: raise HTTPException(401,'Please sign in.')
        if roles and u['role'] not in roles: raise HTTPException(403,'Access denied for this interface.')
        if request.method in ('POST','PUT','PATCH','DELETE') and request.headers.get('X-CSRF-Token') != u['csrf']:
            raise HTTPException(403,'Security token missing. Reload the page.')
        return u
    return inner

def issue_session(response:Response, uid:int):
    token=secrets.token_urlsafe(42); csrf=secrets.token_urlsafe(24)
    with db() as c:
        c.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires) VALUES(?,?,?,?)',
                  (hashlib.sha256(token.encode()).hexdigest(),uid,csrf,int(time.time())+7*86400))
        c.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),))
    response.set_cookie(COOKIE_NAME,token,httponly=True,secure=SECURE_COOKIES,samesite='lax',max_age=7*86400,path='/')
    return csrf

def settings_dict(c): return {r['key']:r['value'] for r in c.execute('SELECT * FROM settings')}
def money_cents(v):
    try: return int((Decimal(str(v))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError): raise HTTPException(400,'Invalid amount')

def calc_quote(c, unit, qty, weight=None):
    s=settings_dict(c)
    subtotal=money_cents(unit)*int(qty)
    fee=(Decimal(subtotal)*Decimal(s['procurement_percent'])/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)
    freight=money_cents(Decimal(str(weight))*Decimal(s['estimated_freight_per_kg_ghs'])) if weight else 0
    handling=money_cents(s['handling_fee_ghs'])
    total=subtotal+int(fee)+handling+freight
    return {'subtotal_cents':subtotal,'procurement_fee_cents':int(fee),'handling_fee_cents':handling,
            'freight_estimate_cents':freight,'total_cents':total, 'currency':'GHS',
            'is_provisional':True,
            'note':'Freight is an estimate only. Final shipping charges may change when the China warehouse measures the parcel. Any adjustment must be confirmed separately.'}

@app.get('/api/public')
def public():
    with db() as c:
        s=settings_dict(c)
        return {'regions':REGIONS, 'rates':{k:s[k] for k in ['procurement_percent','handling_fee_ghs','estimated_freight_per_kg_ghs','ship_for_me_handling_ghs','currency']},
                'contact':{k:s[k] for k in ['support_email','support_phone','china_warehouse_address','ghana_hub']},
                'notice':s['notice'], 'demo':DEMO}

@app.get('/api/quote')
def quote(unit_price:Decimal=Query(gt=0), quantity:int=Query(ge=1,le=10000),weight:Optional[float]=Query(None,gt=0)):
    with db() as c:return calc_quote(c,unit_price,quantity,weight)

@app.post('/api/auth/register')
def register(body:Signup,request:Request,response:Response):
    limited('signup:'+request.client.host,7,3600)
    email=body.email.lower().strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): raise HTTPException(400,'Provide a valid email address.')
    if body.region not in REGIONS: raise HTTPException(400,'Select a Ghana region.')
    if not any(c.isalpha() for c in body.password) or not any(c.isdigit() for c in body.password):raise HTTPException(400,'Use a password with letters and numbers.')
    with db() as c:
        try: uid=insert_user(c,body.full_name.strip(),email,body.password,'customer',body.region,body.phone.strip(),body.district.strip())
        except sqlite3.IntegrityError: raise HTTPException(409,'This email is already registered.')
        u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        notify(c,uid,'Welcome to Combah','Your personal shipping reference is '+u['customer_id']+'. Your full China warehouse address will appear when configured by Combah.')
        event(c,'customer',uid,uid,'ACCOUNT_CREATED','Self-registration')
    csrf=issue_session(response,uid)
    return {'user':user_public(u),'csrf':csrf}

@app.post('/api/auth/login')
def login(body:Login,request:Request,response:Response):
    limited('login:'+request.client.host,20,900)
    with db() as c:
        u=c.execute('SELECT * FROM users WHERE email=? AND is_active=1',(body.email.strip().lower(),)).fetchone()
        if not u or not check_password(body.password,u['password']):raise HTTPException(401,'Incorrect email or password.')
    csrf=issue_session(response,u['id'])
    return {'user':user_public(u),'csrf':csrf}

@app.get('/api/me')
def me(u=Depends(require())):return {'user':user_public(u),'csrf':u['csrf']}

@app.post('/api/auth/logout')
def logout(request:Request,response:Response,u=Depends(require())):
    token=request.cookies.get(COOKIE_NAME)
    if token:
        with db() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie(COOKIE_NAME,path='/')
    return {'ok':True}

@app.put('/api/profile')
def update_profile(body:Profile,u=Depends(require())):
    if body.region and body.region not in REGIONS:raise HTTPException(400,'Invalid region.')
    with db() as c:
        c.execute('UPDATE users SET full_name=?,phone=?,region=?,district=?,address=? WHERE id=?',
                  (body.full_name,body.phone,body.region,body.district,body.address,u['id']))
        updated=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()
    return user_public(updated)

@app.get('/api/notifications')
def notifications(u=Depends(require())):
    with db() as c:return rows(c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50',(u['id'],)))

@app.post('/api/notifications/read')
def read_notifications(u=Depends(require())):
    with db() as c:c.execute('UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL',(now(),u['id']))
    return {'ok':True}

@app.get('/api/ship-requests')
def get_ship_requests(u=Depends(require())):
    with db() as c:
        sql="""SELECT r.*,usr.customer_id AS customer_ref,usr.full_name AS customer_name,
          p.package_ref,p.status AS package_status FROM ship_requests r JOIN users usr ON usr.id=r.customer_id
          LEFT JOIN packages p ON p.id=r.matched_package_id"""
        if u['role']=='customer':
            return rows(c.execute(sql+' WHERE r.customer_id=? ORDER BY r.id DESC',(u['id'],)))
        return rows(c.execute(sql+' ORDER BY r.id DESC LIMIT 500'))

@app.post('/api/ship-requests')
def new_ship_request(body:ShipRequestIn,u=Depends(require('customer'))):
    if body.region not in REGIONS:raise HTTPException(400,'Select a valid destination region.')
    if body.delivery_type not in ('pickup','delivery'):raise HTTPException(400,'Select pickup or delivery.')
    tracking=body.supplier_tracking.strip()
    with db() as c:
        if tracking and c.execute("SELECT 1 FROM ship_requests WHERE customer_id=? AND supplier_tracking=? AND status='PRE_REGISTERED'",(u['id'],tracking)).fetchone():
            raise HTTPException(409,'You already have a pending Ship for Me request using this supplier tracking number.')
        t=now()
        c.execute("""INSERT INTO ship_requests(customer_id,product_name,supplier,supplier_tracking,estimated_weight,
          quantity,region,district,delivery_type,notes,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(u['id'],body.product_name.strip(),body.supplier.strip(),tracking,
          body.estimated_weight,body.quantity,body.region,body.district.strip(),body.delivery_type,body.notes.strip(),t,t))
        rid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        ref=f'CMB-SFM-{rid:06d}'
        c.execute('UPDATE ship_requests SET request_ref=? WHERE id=?',(ref,rid))
        event(c,'ship_request',rid,u['id'],'PRE_REGISTERED',tracking)
        notify(c,u['id'],'Ship for Me request saved',f'{ref} has been preregistered. Wait for Combah to confirm the full China warehouse address before sending goods.')
    return {'id':rid,'request_ref':ref,'status':'PRE_REGISTERED'}

@app.post('/api/ship-requests/{id}/cancel')
def cancel_ship_request(id:int,u=Depends(require('customer'))):
    with db() as c:
        item=c.execute('SELECT * FROM ship_requests WHERE id=? AND customer_id=?',(id,u['id'])).fetchone()
        if not item:raise HTTPException(404,'Request not found.')
        if item['status']!='PRE_REGISTERED':raise HTTPException(409,'Only unmatched preregistrations can be cancelled.')
        c.execute("UPDATE ship_requests SET status='CANCELLED',updated_at=? WHERE id=?",(now(),id))
        event(c,'ship_request',id,u['id'],'CANCELLED','Customer cancelled preregistration')
    return {'ok':True}

@app.get('/api/orders')
def get_orders(u=Depends(require())):
    with db() as c:
        sql='''SELECT o.*,p.status AS payment_status,p.customer_reference AS payment_customer_reference,p.method AS payment_method,
          usr.customer_id AS customer_ref, usr.full_name AS customer_name FROM orders o JOIN users usr ON usr.id=o.customer_id
          LEFT JOIN payments p ON p.order_id=o.id'''
        if u['role']=='customer': return rows(c.execute(sql+' WHERE o.customer_id=? ORDER BY o.id DESC',(u['id'],)))
        if u['role']=='admin': return rows(c.execute(sql+' ORDER BY o.id DESC LIMIT 500'))
        raise HTTPException(403,'Warehouse access is limited to packages.')

@app.get('/api/orders/{id}')
def get_order(id:int,u=Depends(require())):
    with db() as c:
        o=c.execute('SELECT * FROM orders WHERE id=?',(id,)).fetchone()
        if not o:raise HTTPException(404,'Order not found.')
        if u['role']=='warehouse' or (u['role']=='customer' and o['customer_id']!=u['id']):raise HTTPException(403,'Access denied.')
        events=rows(c.execute('SELECT e.event,e.detail,e.created_at,usr.full_name AS by_name FROM events e LEFT JOIN users usr ON usr.id=e.actor_id WHERE entity_type=? AND entity_id=? ORDER BY e.id DESC',('order',id)))
        return {'order':row(o),'timeline':events}

@app.post('/api/orders')
def create_order(body:OrderIn,u=Depends(require('customer'))):
    if body.region not in REGIONS:raise HTTPException(400,'Select a valid Ghana region.')
    if body.delivery_type not in ('pickup','delivery'):raise HTTPException(400,'Invalid delivery method.')
    if not body.product_url.startswith(('https://','http://')):raise HTTPException(400,'Provide a valid product link.')
    with db() as c:
        q=calc_quote(c,body.unit_price,body.quantity,body.estimated_weight)
        t=now()
        c.execute('''INSERT INTO orders(customer_id,product_url,product_name,unit_price_cents,quantity,estimated_weight,
          region,district,delivery_type,notes,procurement_fee_cents,handling_fee_cents,freight_estimate_cents,total_cents,
          quote_note,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (u['id'],body.product_url,body.product_name,money_cents(body.unit_price),body.quantity,body.estimated_weight,
           body.region,body.district,body.delivery_type,body.notes,q['procurement_fee_cents'],q['handling_fee_cents'],
           q['freight_estimate_cents'],q['total_cents'],q['note'],'AWAITING_PAYMENT',t,t))
        oid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        ref=f'CMB-ORD-{oid:06d}'
        c.execute('UPDATE orders SET order_ref=? WHERE id=?',(ref,oid))
        c.execute('INSERT INTO payments(payment_ref,order_id,amount_cents,created_at) VALUES(?,?,?,?)',
                  (f'CMB-PAY-{oid:06d}',oid,q['total_cents'],t))
        event(c,'order',oid,u['id'],'PROCUREMENT_REQUEST','New Buy for Me request')
        notify(c,u['id'],'Request created',f'{ref} is awaiting payment. Use the payment instructions provided by Combah before sending a reference.')
    return {'id':oid,'order_ref':ref,'quote':q,'status':'AWAITING_PAYMENT'}

@app.get('/api/orders/{id}/pdf')
def order_pdf(id:int, kind:str='quote', u=Depends(require())):
    """Download a provisional quotation or a verified-payment acknowledgment."""
    if kind not in ('quote','receipt'):raise HTTPException(400,'Document type not supported.')
    if u['role']=='warehouse':raise HTTPException(403,'Access denied.')
    with db() as c:
        info=c.execute('''SELECT o.*, usr.full_name,usr.customer_id AS customer_ref,
            p.status AS payment_status,p.payment_ref,p.customer_reference,p.reviewed_at
            FROM orders o JOIN users usr ON usr.id=o.customer_id
            JOIN payments p ON p.order_id=o.id WHERE o.id=?''',(id,)).fetchone()
        if not info:raise HTTPException(404,'Order not found.')
        if u['role']=='customer' and info['customer_id']!=u['id']:raise HTTPException(403,'Access denied.')
        if kind=='receipt' and info['payment_status']!='VERIFIED':raise HTTPException(409,'A receipt is only available after payment verification.')
        info=dict(info)
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
    from reportlab.lib.units import mm
    from xml.sax.saxutils import escape
    buffer=BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=A4,leftMargin=22*mm,rightMargin=22*mm,topMargin=20*mm,bottomMargin=20*mm)
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CombahTitle',parent=styles['Heading1'],fontSize=20,leading=25,textColor=colors.HexColor('#0a3439'),spaceAfter=5))
    styles.add(ParagraphStyle(name='CombahNote',parent=styles['Normal'],fontSize=8,leading=11,textColor=colors.HexColor('#657b80')))
    plain=lambda t:escape(str(t or '—'))
    amount=lambda n:f'GHS {n/100:,.2f}'
    text=[Paragraph('COMBAH <font color="#c09c60">.</font>',styles['CombahTitle']),
        Paragraph('PROCUREMENT &amp; LOGISTICS  |  CHINA TO GHANA',styles['CombahNote']),Spacer(1,15*mm),
        Paragraph('PAYMENT ACKNOWLEDGMENT' if kind=='receipt' else 'PROVISIONAL PROCUREMENT QUOTATION',styles['Heading2']),Spacer(1,3*mm)]
    fields=[('Order reference',info['order_ref']),('Customer',info['full_name']),('Customer ID',info['customer_ref']),
      ('Issue date',now()[:10]),('Product',info['product_name']),('Quantity',str(info['quantity'])),('Destination region',info['region'])]
    if kind=='receipt':fields.extend([('Payment record',info['payment_ref']),('Reference submitted',info['customer_reference']),('Verified on',(info['reviewed_at'] or '')[:10])])
    t=Table([[Paragraph(plain(k),styles['CombahNote']),Paragraph(plain(v),styles['Normal'])] for k,v in fields],colWidths=[42*mm,120*mm])
    t.setStyle(TableStyle([('BOTTOMPADDING',(0,0),(-1,-1),9),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-2),.25,colors.HexColor('#e6eae8'))]))
    text.extend([t,Spacer(1,8*mm)])
    charges=[('Product subtotal',info['unit_price_cents']*info['quantity']),('Procurement fee',info['procurement_fee_cents']),
      ('Handling fee',info['handling_fee_cents']),('Estimated freight',info['freight_estimate_cents']),
      ('TOTAL RECORDED' if kind=='receipt' else 'PROVISIONAL QUOTATION TOTAL',info['total_cents'])]
    tab=Table([[label,amount(cents)] for label,cents in charges],colWidths=[105*mm,57*mm])
    tab.setStyle(TableStyle([('LINEABOVE',(0,-1),(-1,-1),1,colors.HexColor('#0b4c4b')),
        ('TEXTCOLOR',(0,-1),(-1,-1),colors.HexColor('#0b4c4b')),('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold'),
        ('ALIGN',(1,0),(1,-1),'RIGHT'),('BOTTOMPADDING',(0,0),(-1,-1),12)]))
    text.extend([tab,Spacer(1,8*mm)])
    note=('Acknowledges a payment verified in Combah records. Not a statutory tax invoice or evidence of delivery.'
          if kind=='receipt' else 'Provisional estimate in Ghana cedis. Final freight and import charges may require adjustment after warehouse measurement and clearance. Not a payment receipt.')
    text.append(Paragraph(plain(note),styles['CombahNote']))
    doc.build(text)
    buffer.seek(0)
    filename=f'{info["order_ref"]}-{kind}.pdf'
    return StreamingResponse(buffer,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'private, no-store'})

@app.post('/api/orders/{id}/payment-reference')
def payment_reference(id:int,body:PaymentRef,u=Depends(require('customer'))):
    with db() as c:
        o=c.execute('SELECT * FROM orders WHERE id=? AND customer_id=?',(id,u['id'])).fetchone()
        if not o:raise HTTPException(404,'Order not found.')
        if o['status']!='AWAITING_PAYMENT':raise HTTPException(409,'Payment reference can no longer be submitted for this order.')
        c.execute('UPDATE payments SET customer_reference=?,method=?,status=? WHERE order_id=?',
                  (body.reference.strip(),body.method,'PENDING_VERIFICATION',id))
        c.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?',('PAYMENT_REVIEW',now(),id))
        event(c,'order',id,u['id'],'PAYMENT_REFERENCE_SUBMITTED',body.reference.strip())
        notify(c,u['id'],'Payment awaiting verification',f'We received your payment reference for {o["order_ref"]}. Staff must verify the payment before procurement starts.')
    return {'ok':True,'status':'PAYMENT_REVIEW'}

@app.get('/api/customer-lookup')
def customer_lookup(customer_id:str,u=Depends(require('warehouse','admin'))):
    with db() as c:
        match=c.execute('SELECT id,customer_id,full_name,region,district FROM users WHERE customer_id=? AND role=? AND is_active=1',(customer_id.strip().upper(),'customer')).fetchone()
    if not match:raise HTTPException(404,'No customer matches that reference.')
    return row(match)

@app.get('/api/packages')
def get_packages(u=Depends(require())):
    with db() as c:
        sql='''SELECT p.*,u.customer_id AS customer_ref,u.full_name AS customer_name,o.order_ref,
         sr.request_ref AS ship_request_ref,sp.shipment_id,s.shipment_ref,s.status AS shipment_status
         FROM packages p JOIN users u ON p.customer_id=u.id
         LEFT JOIN orders o ON p.order_id=o.id
         LEFT JOIN ship_requests sr ON sr.matched_package_id=p.id
         LEFT JOIN shipment_packages sp ON p.id=sp.package_id
         LEFT JOIN shipments s ON s.id=sp.shipment_id'''
        if u['role']=='customer':return rows(c.execute(sql+' WHERE p.customer_id=? ORDER BY p.id DESC',(u['id'],)))
        return rows(c.execute(sql+' ORDER BY p.id DESC LIMIT 1000'))

@app.post('/api/packages')
def create_pkg(body:PkgIn,u=Depends(require('warehouse','admin'))):
    if body.order_ref.strip() and body.ship_request_ref.strip():raise HTTPException(400,'A package can be linked to Buy for Me or Ship for Me, not both.')
    if body.order_ref and not re.fullmatch(r'CMB-ORD-\d{6}',body.order_ref.strip().upper()):raise HTTPException(400,'Invalid order reference.')
    with db() as c:
        owner=c.execute('SELECT * FROM users WHERE customer_id=? AND role=?',(body.customer_id.upper().strip(),'customer')).fetchone()
        if not owner:raise HTTPException(404,'Customer ID not found.')
        order_id=None
        if body.order_ref:
            order=c.execute('SELECT * FROM orders WHERE order_ref=? AND customer_id=?',(body.order_ref.strip().upper(),owner['id'])).fetchone()
            if not order:raise HTTPException(404,'Order does not belong to this customer.')
            order_id=order['id']
        request_item=None
        if body.ship_request_ref.strip():
            request_item=c.execute("SELECT * FROM ship_requests WHERE request_ref=? AND customer_id=? AND status='PRE_REGISTERED'",
              (body.ship_request_ref.strip().upper(),owner['id'])).fetchone()
            if not request_item:raise HTTPException(409,'No pending Ship for Me preregistration matches this customer and reference.')
        elif body.tracking_number.strip():
            candidates=c.execute("SELECT * FROM ship_requests WHERE customer_id=? AND supplier_tracking=? AND status='PRE_REGISTERED'",
              (owner['id'],body.tracking_number.strip())).fetchall()
            if len(candidates)==1:request_item=candidates[0]
        if request_item and body.tracking_number.strip() and request_item['supplier_tracking'] and body.tracking_number.strip()!=request_item['supplier_tracking']:
            raise HTTPException(409,'Supplier tracking differs from the customer preregistration; confirm the correct parcel before matching.')
        duplicate=c.execute("SELECT package_ref FROM packages WHERE customer_id=? AND tracking_number=? AND tracking_number<>'' ORDER BY id DESC LIMIT 1",
          (owner['id'],body.tracking_number.strip())).fetchone() if body.tracking_number.strip() else None
        t=now()
        c.execute('''INSERT INTO packages(customer_id,order_id,supplier,tracking_number,description,weight_kg,length_cm,width_cm,height_cm,count,damaged,notes,status,received_by,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (owner['id'],order_id,body.supplier,body.tracking_number,body.description,body.weight_kg,body.length_cm,body.width_cm,body.height_cm,
           body.count,int(body.damaged),body.notes,'RECEIVED_IN_CHINA',u['id'],t,t))
        pid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        ref=f'CMB-PKG-{pid:06d}'
        c.execute('UPDATE packages SET package_ref=? WHERE id=?',(ref,pid))
        if request_item:
            c.execute("UPDATE ship_requests SET status='RECEIVED_IN_CHINA',matched_package_id=?,updated_at=? WHERE id=? AND status='PRE_REGISTERED'",
              (pid,t,request_item['id']))
            event(c,'ship_request',request_item['id'],u['id'],'RECEIVED_IN_CHINA',ref)
        if order_id:
            c.execute('UPDATE orders SET status=?,updated_at=? WHERE id=? AND status IN (?,?,?)',
                      ('RECEIVED_IN_CHINA',t,order_id,'PROCUREMENT','SUPPLIER_DISPATCH','OFFICER_REVIEW'))
            event(c,'order',order_id,u['id'],'RECEIVED_IN_CHINA',ref)
        event(c,'package',pid,u['id'],'RECEIVED_IN_CHINA',body.tracking_number)
        notify(c,owner['id'],'Package received in China',f'{ref} has been registered at the Combah China warehouse.')
    return {'id':pid,'package_ref':ref,'matched_ship_request':request_item['request_ref'] if request_item else None, 'duplicate_warning':f'Supplier tracking has already been used for {duplicate["package_ref"]}; verify that this is a separate physical parcel.' if duplicate else None}

@app.patch('/api/packages/{id}')
def update_pkg(id:int,body:PkgUpdate,u=Depends(require('warehouse','admin'))):
    if body.status not in PACKAGE_STATES:raise HTTPException(400,'Invalid package status.')
    with db() as c:
        p=c.execute('SELECT * FROM packages WHERE id=?',(id,)).fetchone()
        if not p:raise HTTPException(404,'Package not found.')
        if body.status!='READY_FOR_SHIPPING' or p['status']!='RECEIVED_IN_CHINA':raise HTTPException(409,'Only warehouse-received packages may be marked ready here. Shipment milestones must be updated through the shipment.')
        if PACKAGE_STATES.index(body.status)<PACKAGE_STATES.index(p['status']):raise HTTPException(409,'Cannot reverse status progression.')
        if c.execute('SELECT 1 FROM shipment_packages WHERE package_id=?',(id,)).fetchone():raise HTTPException(409,'Package already belongs to a shipment.')
        if p['damaged'] and body.damaged is not False:
            raise HTTPException(409,'Damaged package is on hold. Confirm inspection and provide a resolution note before marking ready.')
        if p['damaged'] and body.damaged is False and len(body.notes.strip())<8:
            raise HTTPException(409,'Record the damage inspection/resolution in the warehouse notes (at least 8 characters).')
        c.execute('UPDATE packages SET status=?,damaged=?,notes=?,updated_at=? WHERE id=?',
                  (body.status,0 if body.damaged is False else p['damaged'],body.notes or p['notes'],now(),id))
        if p['damaged'] and body.damaged is False:
            event(c,'package',id,u['id'],'DAMAGE_RESOLVED',body.notes)
        event(c,'package',id,u['id'],body.status,body.notes)
        notify(c,p['customer_id'],'Package update',f'{p["package_ref"]}: {body.status.replace("_"," ").title()}.')
    return {'ok':True}

@app.get('/api/shipments')
def get_shipments(u=Depends(require())):
    with db() as c:
        sql='''SELECT s.*,GROUP_CONCAT(p.package_ref,', ') AS packages,
            COUNT(p.id) AS package_count FROM shipments s
            LEFT JOIN shipment_packages sp ON s.id=sp.shipment_id
            LEFT JOIN packages p ON p.id=sp.package_id'''
        if u['role']=='customer':
            return rows(c.execute(sql+' WHERE EXISTS(SELECT 1 FROM shipment_packages x JOIN packages y ON x.package_id=y.id WHERE x.shipment_id=s.id AND y.customer_id=?) GROUP BY s.id ORDER BY s.id DESC',(u['id'],)))
        if u['role']=='warehouse':raise HTTPException(403,'Shipments are managed by Ghana operations.')
        return rows(c.execute(sql+' GROUP BY s.id ORDER BY s.id DESC LIMIT 500'))

@app.get('/api/shipments/{id}/timeline')
def shipment_timeline(id:int,u=Depends(require('customer','admin'))):
    with db() as c:
        sh=c.execute('SELECT * FROM shipments WHERE id=?',(id,)).fetchone()
        if not sh:raise HTTPException(404,'Shipment not found.')
        if u['role']=='customer':
            owned=c.execute('''SELECT 1 FROM shipment_packages sp JOIN packages p ON p.id=sp.package_id
               WHERE sp.shipment_id=? AND p.customer_id=? LIMIT 1''',(id,u['id'])).fetchone()
            if not owned:raise HTTPException(403,'Access denied.')
        events=rows(c.execute('''SELECT event,detail,created_at FROM events WHERE entity_type='shipment'
            AND entity_id=? ORDER BY id ASC''',(id,)))
    return {'shipment':row(sh),'timeline':events}

@app.post('/api/shipments')
def create_shipment(body:ShipIn,u=Depends(require('admin'))):
    if body.destination_region not in REGIONS:raise HTTPException(400,'Select a destination region.')
    with db() as c:
        ids=list(dict.fromkeys(body.package_ids))
        records=rows(c.execute('SELECT * FROM packages WHERE id IN ('+','.join('?'*len(ids))+')',ids))
        if len(records)!=len(ids):raise HTTPException(404,'Some packages could not be found.')
        busy=rows(c.execute('SELECT package_id FROM shipment_packages WHERE package_id IN ('+','.join('?'*len(ids))+')',ids))
        if busy:raise HTTPException(409,'Some packages already belong to a shipment.')
        if any(p['status']!='READY_FOR_SHIPPING' for p in records):
            raise HTTPException(409,'Each package must be inspected and marked Ready for Shipping by warehouse staff before consolidation.')
        if any(p['damaged'] for p in records):
            raise HTTPException(409,'Damaged parcels must be resolved before being assigned to a shipment.')
        t=now()
        c.execute('''INSERT INTO shipments(carrier,tracking_number,destination_region,eta,notes,status,created_by,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?)''',(body.carrier,body.tracking_number,body.destination_region,body.eta,body.notes,'READY_FOR_SHIPPING',u['id'],t,t))
        sid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        ref=f'CMB-SHP-{sid:06d}'
        c.execute('UPDATE shipments SET shipment_ref=? WHERE id=?',(ref,sid))
        for p in records:
            c.execute('INSERT INTO shipment_packages(shipment_id,package_id) VALUES(?,?)',(sid,p['id']))
            c.execute('UPDATE packages SET status=?,updated_at=? WHERE id=?',('READY_FOR_SHIPPING',t,p['id']))
            if p['order_id']:
                c.execute('UPDATE orders SET status=?,updated_at=? WHERE id=? AND status=?',
                          ('READY_FOR_SHIPPING',t,p['order_id'],'RECEIVED_IN_CHINA'))
                event(c,'order',p['order_id'],u['id'],'READY_FOR_SHIPPING',ref)
            notify(c,p['customer_id'],'Shipment scheduled',f'{p["package_ref"]} has been assigned to {ref}.')
        event(c,'shipment',sid,u['id'],'READY_FOR_SHIPPING',f'{len(records)} packages')
    return {'id':sid,'shipment_ref':ref}

@app.patch('/api/shipments/{id}')
def update_shipment(id:int,body:ShipUpdate,u=Depends(require('admin'))):
    if body.status not in SHIP_STATES:raise HTTPException(400,'Invalid shipment status.')
    with db() as c:
        sh=c.execute('SELECT * FROM shipments WHERE id=?',(id,)).fetchone()
        if not sh:raise HTTPException(404,'Shipment not found.')
        a=SHIP_STATES.index(sh['status']); b=SHIP_STATES.index(body.status)
        if b<a or b>a+1:raise HTTPException(409,'Move shipment through statuses in order.')
        carrier=(body.carrier if body.carrier is not None else sh['carrier']).strip()
        track=(body.tracking_number if body.tracking_number is not None else sh['tracking_number']).strip()
        if b>=SHIP_STATES.index('IN_TRANSIT') and not (carrier or track):
            raise HTTPException(409,'Enter the freight carrier/service or a dispatch tracking reference before marking the shipment In Transit.')
        c.execute('UPDATE shipments SET status=?,carrier=?,tracking_number=?,eta=?,notes=?,updated_at=? WHERE id=?',
                  (body.status,carrier,track,
                   body.eta if body.eta is not None else sh['eta'],
                   body.notes if body.notes is not None else sh['notes'],now(),id))
        packages=rows(c.execute('SELECT p.* FROM packages p JOIN shipment_packages sp ON p.id=sp.package_id WHERE sp.shipment_id=?',(id,)))
        for p in packages:
            c.execute('UPDATE packages SET status=?,updated_at=? WHERE id=?',(body.status,now(),p['id']))
            if p['order_id']:
                c.execute('UPDATE orders SET status=?,updated_at=? WHERE id=? AND status NOT IN (?,?,?)',
                          (body.status,now(),p['order_id'],'AWAITING_PAYMENT','PAYMENT_REVIEW','CANCELLED'))
                event(c,'order',p['order_id'],u['id'],body.status,sh['shipment_ref'])
            notify(c,p['customer_id'],'Shipment tracking update',f'{sh["shipment_ref"]}: {body.status.replace("_"," ").title()}.')
        if b>a or carrier!=sh['carrier'] or track!=sh['tracking_number']:
            event(c,'shipment',id,u['id'],body.status,'Freight service: '+(carrier or 'Not assigned')+' | Ref: '+(track or 'Pending'))
    return {'ok':True}

@app.get('/api/admin/overview')
def overview(u=Depends(require('admin'))):
    with db() as c:
        return {'customers':c.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0],
          'orders':c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],
          'pending_payments':c.execute("SELECT COUNT(*) FROM payments WHERE status='PENDING_VERIFICATION'").fetchone()[0],
          'china_packages':c.execute("SELECT COUNT(*) FROM packages WHERE status IN ('RECEIVED_IN_CHINA','READY_FOR_SHIPPING')").fetchone()[0],
          'in_transit':c.execute("SELECT COUNT(*) FROM shipments WHERE status='IN_TRANSIT'").fetchone()[0],
          'shipments':c.execute('SELECT COUNT(*) FROM shipments').fetchone()[0],
          'verified_volume_cents':c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE status='VERIFIED'").fetchone()[0]}

@app.get('/api/admin/customers')
def customers(u=Depends(require('admin'))):
    with db() as c:return rows(c.execute('SELECT id,customer_id,full_name,email,phone,role,region,district,created_at,is_active FROM users ORDER BY id DESC LIMIT 500'))

@app.get('/api/admin/payments')
def payments(u=Depends(require('admin'))):
    with db() as c:return rows(c.execute('''SELECT p.*,o.order_ref,o.customer_id AS customer_pk,usr.full_name AS customer_name,usr.customer_id AS customer_ref
       FROM payments p JOIN orders o ON o.id=p.order_id JOIN users usr ON usr.id=o.customer_id ORDER BY p.id DESC LIMIT 500'''))

@app.post('/api/admin/payments/{id}/decision')
def payment_decision(id:int,body:PaymentDecision,u=Depends(require('admin'))):
    with db() as c:
        p=c.execute('SELECT p.*,o.order_ref,o.customer_id FROM payments p JOIN orders o ON o.id=p.order_id WHERE p.id=?',(id,)).fetchone()
        if not p:raise HTTPException(404,'Payment not found.')
        if p['status']!='PENDING_VERIFICATION':raise HTTPException(409,'Payment is not pending verification.')
        status='VERIFIED' if body.approved else 'REJECTED'
        os='OFFICER_REVIEW' if body.approved else 'AWAITING_PAYMENT'
        c.execute('UPDATE payments SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?',(status,u['id'],now(),id))
        c.execute('UPDATE orders SET status=?,staff_note=?,updated_at=? WHERE id=?',(os,body.note,now(),p['order_id']))
        event(c,'order',p['order_id'],u['id'],'PAYMENT_'+status,body.note)
        notify(c,p['customer_id'],'Payment '+('verified' if body.approved else 'not verified'),
               f'{p["order_ref"]}: '+('Your request is now with the procurement team.' if body.approved else 'Please contact Combah and submit a correct payment reference.'))
    return {'ok':True}

@app.patch('/api/admin/orders/{id}')
def order_update(id:int,body:OrderUpdate,u=Depends(require('admin'))):
    valid=['OFFICER_REVIEW','PROCUREMENT','SUPPLIER_DISPATCH','CANCELLED']
    if body.status not in valid:raise HTTPException(400,'Invalid procurement status.')
    with db() as c:
        o=c.execute('SELECT * FROM orders WHERE id=?',(id,)).fetchone()
        if not o:raise HTTPException(404,'Order not found.')
        if o['status'] in ('AWAITING_PAYMENT','PAYMENT_REVIEW'):
            raise HTTPException(409,'Payment must first be verified.')
        if body.status=='CANCELLED' and o['status'] not in ('OFFICER_REVIEW','PROCUREMENT','SUPPLIER_DISPATCH'):
            raise HTTPException(409,'Cannot cancel an order after it has entered the warehouse or logistics workflow.')
        if body.status!='CANCELLED':
            possible={'OFFICER_REVIEW':['PROCUREMENT'], 'PROCUREMENT':['SUPPLIER_DISPATCH'], 'SUPPLIER_DISPATCH':[]}
            if body.status!=o['status'] and body.status not in possible.get(o['status'],[]):
                raise HTTPException(409,'Invalid status progression for procurement.')
        c.execute('UPDATE orders SET status=?,supplier_tracking=?,staff_note=?,updated_at=? WHERE id=?',
                 (body.status,body.supplier_tracking if body.supplier_tracking is not None else o['supplier_tracking'],
                  body.staff_note if body.staff_note is not None else o['staff_note'],now(),id))
        event(c,'order',id,u['id'],body.status,body.staff_note or '')
        notify(c,o['customer_id'],'Procurement update',f'{o["order_ref"]}: {body.status.replace("_"," ").title()}.')
    return {'ok':True}

@app.get('/api/admin/audit')
def audits(u=Depends(require('admin'))):
    with db() as c:return rows(c.execute('''SELECT e.*,u.full_name AS actor_name FROM events e LEFT JOIN users u ON u.id=e.actor_id ORDER BY e.id DESC LIMIT 150'''))

@app.get('/api/admin/settings')
def get_settings(u=Depends(require('admin'))):
    with db() as c:return settings_dict(c)

@app.put('/api/admin/settings')
async def put_settings(request:Request,u=Depends(require('admin'))):
    body=await request.json()
    allowed={'procurement_percent','handling_fee_ghs','estimated_freight_per_kg_ghs','ship_for_me_handling_ghs','support_email','support_phone',
             'china_warehouse_address','ghana_hub','notice'}
    with db() as c:
        for k,v in body.items():
            if k not in allowed:raise HTTPException(400,f'Cannot update setting: {k}')
            if not isinstance(v,str) or len(v)>1000:raise HTTPException(400,'Invalid setting value.')
            if k in {'procurement_percent','handling_fee_ghs','estimated_freight_per_kg_ghs','ship_for_me_handling_ghs'}:
                try:
                    n=Decimal(v)
                    if not n.is_finite() or n<0 or n>100000:raise ValueError()
                except (InvalidOperation,ValueError):raise HTTPException(400,f'Invalid numeric rate: {k}')
            c.execute('UPDATE settings SET value=? WHERE key=?',(v,k))
        event(c,'settings',0,u['id'],'SETTINGS_UPDATED',','.join(body.keys()))
        return settings_dict(c)

@app.post('/api/admin/staff')
def add_staff(body:StaffIn,u=Depends(require('admin'))):
    if body.role not in ('admin','warehouse'):raise HTTPException(400,'Invalid staff role.')
    email=body.email.lower().strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise HTTPException(400,'Invalid email.')
    with db() as c:
        try: uid=insert_user(c,body.full_name,email,body.password,body.role)
        except sqlite3.IntegrityError:raise HTTPException(409,'Email already exists.')
        event(c,'user',uid,u['id'],'STAFF_CREATED',body.role)
    return {'id':uid}

@app.get('/api/health')
def health():return {'status':'ok'}

# No public API that allows arbitrary updates to account roles, settings, records, or verified payments.
app.mount('/assets',StaticFiles(directory=str(ROOT/'static')),name='assets')

@app.get('/')
@app.get('/login')
@app.get('/register')
@app.get('/app')
@app.get('/app/{slug:path}')
def frontend(slug:str=''):
    return FileResponse(str(ROOT/'static'/'index.html'),headers={'Cache-Control':'no-store'})
