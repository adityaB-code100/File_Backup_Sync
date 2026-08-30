import pytest
import mongoengine as me
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from accounts.models import User

@override_settings(MONGO_URI='mongodb://localhost:27017/cloud_storage_test_db')
class AccountsAuthTestCase(TestCase):
    def setUp(self):
        me.disconnect()
        me.connect('cloud_storage_test_db', host='mongodb://localhost:27017/cloud_storage_test_db')
        User.objects.delete()
        self.client = APIClient()

    def tearDown(self):
        User.objects.delete()
        me.disconnect()

    def test_register_login_refresh_flow(self):
        # 1. Register User
        reg_resp = self.client.post('/api/auth/register/', {
            'email': 'testuser@example.com',
            'password': 'StrongPassword123!'
        }, format='json')
        self.assertEqual(reg_resp.status_code, 201)
        self.assertIn('access', reg_resp.data)
        self.assertIn('refresh', reg_resp.data)
        self.assertEqual(reg_resp.data['user']['email'], 'testuser@example.com')

        # 2. Login User
        login_resp = self.client.post('/api/auth/login/', {
            'email': 'testuser@example.com',
            'password': 'StrongPassword123!'
        }, format='json')
        self.assertEqual(login_resp.status_code, 200)
        access_token = login_resp.data['access']
        refresh_token = login_resp.data['refresh']

        # 3. Access Protected Route (/api/auth/me/)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        me_resp = self.client.get('/api/auth/me/')
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.data['email'], 'testuser@example.com')

        # 4. Refresh Token Flow
        ref_resp = self.client.post('/api/auth/refresh/', {
            'refresh': refresh_token
        }, format='json')
        self.assertEqual(ref_resp.status_code, 200)
        self.assertIn('access', ref_resp.data)
