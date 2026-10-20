"""Isolated API smoke test: python -m unittest discover -s tests -v
Requires httpx (pip install -r requirements-dev.txt).
"""
import os, tempfile, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
ROOT=tempfile.TemporaryDirectory(prefix='combah-test-')
os.environ['COMBAH_DATA_DIR']=ROOT.name
os.environ['COMBAH_DEMO']='1'
from fastapi.testclient import TestClient
from app import app

class WorkflowTests(unittest.TestCase):
    def setUp(self):self.client=TestClient(app)
    def auth(self,role):
        resp=self.client.post('/api/auth/login',json={'email':role+'@combah.demo','password':'DemoPass!2026'})
        self.assertEqual(resp.status_code,200,resp.text)
        return {'X-CSRF-Token':resp.json()['csrf']}

    def test_permissions_and_crsf(self):
        h=self.auth('customer')
        self.assertEqual(self.client.get('/api/admin/overview').status_code,403)
        self.assertEqual(self.client.post('/api/orders',json={}).status_code,403)
        self.assertEqual(self.client.get('/api/orders').status_code,200)
        self.assertEqual(self.client.post('/api/packages',json={'customer_id':'CMB-GH-000003'},headers=h).status_code,403)

    def test_procurement_warehouse_shipping(self):
        h=self.auth('customer')
        r=self.client.post('/api/orders',json={'product_url':'https://example.com/fan','product_name':'Industrial fan','unit_price':125,'quantity':2,'region':'Northern','delivery_type':'pickup'},headers=h)
        self.assertEqual(r.status_code,200,r.text); order=r.json()
        self.assertEqual(order['quote']['subtotal_cents'],25000)
        oid=order['id']
        r=self.client.post(f'/api/orders/{oid}/payment-reference',json={'reference':'TRF-TEST-1111','method':'bank_transfer'},headers=h)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get(f'/api/orders/{oid}/pdf?kind=receipt').status_code,409)
        self.client.post('/api/auth/logout',headers=h)
        ah=self.auth('admin')
        pay=next(x for x in self.client.get('/api/admin/payments').json() if x['order_id']==oid)
        r=self.client.post(f'/api/admin/payments/{pay["id"]}/decision',json={'approved':True},headers=ah)
        self.assertEqual(r.status_code,200,r.text)
        for status in ['PROCUREMENT','SUPPLIER_DISPATCH']:
            r=self.client.patch(f'/api/admin/orders/{oid}',json={'status':status,'carrier':'Combah Consolidated Air'},headers=ah)
            self.assertEqual(r.status_code,200,r.text)
        self.client.post('/api/auth/logout',headers=ah)
        wh=self.auth('warehouse')
        r=self.client.get('/api/customer-lookup?customer_id=CMB-GH-000003')
        self.assertEqual(r.status_code,200)
        r=self.client.post('/api/packages',json={'customer_id':'CMB-GH-000003','order_ref':order['order_ref'],'description':'Fan carton','weight_kg':4.2},headers=wh)
        self.assertEqual(r.status_code,200,r.text); pkg=r.json()
        self.assertEqual(self.client.post('/api/shipments',json={'package_ids':[pkg['id']],'destination_region':'Northern'},headers=wh).status_code,403)
        r=self.client.patch(f'/api/packages/{pkg["id"]}',json={'status':'READY_FOR_SHIPPING'},headers=wh)
        self.assertEqual(r.status_code,200,r.text)
        self.client.post('/api/auth/logout',headers=wh)
        ah=self.auth('admin')
        r=self.client.post('/api/shipments',json={'package_ids':[pkg['id']],'destination_region':'Northern'},headers=ah)
        self.assertEqual(r.status_code,200,r.text); sid=r.json()['id']
        self.assertEqual(self.client.post('/api/shipments',json={'package_ids':[pkg['id']],'destination_region':'Northern'},headers=ah).status_code,409)
        for status in ['IN_TRANSIT','ARRIVED_GHANA','CLEARANCE','DISPATCHED_TO_REGION','READY_FOR_COLLECTION','COMPLETED']:
            r=self.client.patch(f'/api/shipments/{sid}',json={'status':status,'carrier':'Combah Consolidated Air'},headers=ah)
            self.assertEqual(r.status_code,200,r.text)
        self.client.post('/api/auth/logout',headers=ah)
        h=self.auth('customer')
        self.assertEqual(self.client.get(f'/api/shipments/{sid}/timeline').status_code,200)
        self.assertTrue(self.client.get(f'/api/orders/{oid}/pdf?kind=quote').content.startswith(b'%PDF'))
        self.assertTrue(self.client.get(f'/api/orders/{oid}/pdf?kind=receipt').content.startswith(b'%PDF'))

    def test_ship_for_me_preregister_and_warehouse_matching(self):
        ch=self.auth('customer')
        request={'product_name':'Laptop accessories','supplier':'Yiwu sample vendor','supplier_tracking':'CN-TEST-111',
                 'quantity':2,'estimated_weight':1.6,'region':'Greater Accra','district':'Accra','delivery_type':'pickup'}
        r=self.client.post('/api/ship-requests',json=request,headers=ch)
        self.assertEqual(r.status_code,200,r.text); sr=r.json()
        self.assertTrue(sr['request_ref'].startswith('CMB-SFM-'))
        assert any(x['id']==sr['id'] and x['status']=='PRE_REGISTERED' for x in self.client.get('/api/ship-requests').json())
        self.assertEqual(self.client.post('/api/ship-requests',json=request,headers=ch).status_code,409)
        self.assertEqual(self.client.get('/api/admin/overview').status_code,403)
        self.client.post('/api/auth/logout',headers=ch)
        wh=self.auth('warehouse')
        self.assertEqual(self.client.post('/api/ship-requests',json=request,headers=wh).status_code,403)
        # Prevent attaching a preregistration to the wrong customer.
        bad=self.client.post('/api/packages',json={'customer_id':'CMB-GH-000004','ship_request_ref':sr['request_ref'],'description':'Accessories'},headers=wh)
        self.assertEqual(bad.status_code,409,bad.text)
        pack=self.client.post('/api/packages',json={'customer_id':'CMB-GH-000003',
           'ship_request_ref':sr['request_ref'],'supplier':'Yiwu sample vendor','tracking_number':'CN-TEST-111',
           'description':'Laptop accessories','weight_kg':1.6},headers=wh)
        self.assertEqual(pack.status_code,200,pack.text)
        pid=pack.json()['id']
        self.assertEqual(pack.json()['matched_ship_request'],sr['request_ref'])
        self.assertEqual(self.client.post('/api/packages',json={'customer_id':'CMB-GH-000003',
           'ship_request_ref':sr['request_ref'],'description':'Duplicate'},headers=wh).status_code,409)
        self.client.post('/api/auth/logout',headers=wh)
        ch=self.auth('customer')
        item=next(x for x in self.client.get('/api/ship-requests').json() if x['id']==sr['id'])
        self.assertEqual(item['status'],'RECEIVED_IN_CHINA')
        self.assertEqual(item['matched_package_id'],pid)
        self.assertEqual(item['package_ref'],pack.json()['package_ref'])
        self.assertEqual(self.client.post(f'/api/ship-requests/{sr["id"]}/cancel',headers=ch).status_code,409)
        self.assertEqual(self.client.get('/api/packages').json()[0]['customer_ref'],'CMB-GH-000003')

    def test_damaged_parcel_requires_documented_resolution(self):
        wh=self.auth('warehouse')
        r=self.client.post('/api/packages',json={'customer_id':'CMB-GH-000003',
            'description':'Damaged carton','damaged':True,'tracking_number':'CN-DAMAGE-001'},headers=wh)
        self.assertEqual(r.status_code,200,r.text)
        pid=r.json()['id']
        url=f'/api/packages/{pid}'
        self.assertEqual(self.client.patch(url,json={'status':'READY_FOR_SHIPPING'},headers=wh).status_code,409)
        self.assertEqual(self.client.patch(url,json={'status':'READY_FOR_SHIPPING','damaged':False,'notes':'ok'},headers=wh).status_code,409)
        r=self.client.patch(url,json={'status':'READY_FOR_SHIPPING','damaged':False,
            'notes':'Repacked and verified carton contents after damage inspection'},headers=wh)
        self.assertEqual(r.status_code,200,r.text)
        pkg=next(x for x in self.client.get('/api/packages').json() if x['id']==pid)
        self.assertEqual(pkg['damaged'],0)
        self.assertEqual(pkg['status'],'READY_FOR_SHIPPING')

    def test_cancel_and_freight_safety(self):
        ch=self.auth('customer')
        data={'product_name':'Small tools','region':'Greater Accra'}
        req=self.client.post('/api/ship-requests',json=data,headers=ch).json()
        self.assertEqual(self.client.post(f'/api/ship-requests/{req["id"]}/cancel',headers=ch).status_code,200)
        self.assertEqual(self.client.post(f'/api/ship-requests/{req["id"]}/cancel',headers=ch).status_code,409)
        self.client.post('/api/auth/logout',headers=ch)
        wh=self.auth('warehouse')
        pack=self.client.post('/api/packages',json={'customer_id':'CMB-GH-000003',
            'description':'Test parcel','tracking_number':'CN-TEST-222','weight_kg':2},headers=wh).json()
        dup=self.client.post('/api/packages',json={'customer_id':'CMB-GH-000003',
            'description':'Second carton','tracking_number':'CN-TEST-222'},headers=wh)
        self.assertEqual(dup.status_code,200,dup.text)
        self.assertIn('already been used',dup.json()['duplicate_warning'])
        self.client.post('/api/auth/logout',headers=wh)
        ah=self.auth('admin')
        payload={'package_ids':[pack['id']],'destination_region':'Greater Accra'}
        self.assertEqual(self.client.post('/api/shipments',json=payload,headers=ah).status_code,409)
        self.client.post('/api/auth/logout',headers=ah)
        wh=self.auth('warehouse')
        self.assertEqual(self.client.patch(f'/api/packages/{pack["id"]}',json={'status':'READY_FOR_SHIPPING'},headers=wh).status_code,200)
        self.client.post('/api/auth/logout',headers=wh)
        ah=self.auth('admin')
        sh=self.client.post('/api/shipments',json=payload,headers=ah)
        self.assertEqual(sh.status_code,200,sh.text)
        sid=sh.json()['id']
        r=self.client.patch(f'/api/shipments/{sid}',json={'status':'IN_TRANSIT'},headers=ah)
        self.assertEqual(r.status_code,409,r.text)
        r=self.client.patch(f'/api/shipments/{sid}',json={'status':'IN_TRANSIT','carrier':'Combah Air'},headers=ah)
        self.assertEqual(r.status_code,200,r.text)
        timeline=self.client.get(f'/api/shipments/{sid}/timeline').json()['timeline']
        self.assertEqual([x['event'] for x in timeline],['READY_FOR_SHIPPING','IN_TRANSIT'])
        self.assertIn('Combah Air',timeline[-1]['detail'])

if __name__=='__main__':unittest.main()
