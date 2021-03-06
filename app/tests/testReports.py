#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
logger = logging.getLogger()

import unittest
import requests
from unitTestConfig import base_plus_endpoint_encoded, headers
from localsecrets import API_KEY_NAME, API_KEY

class TestReports(unittest.TestCase):
    """
    Note: tests are performed in alphabetical order, hence the function naming
          with forced order in the names.
          
    """   

    #TODO: Later these will need to be done while logged in.
    
    def test01_session_log_report_daterange(self):
        # note api_key is required, but already in headers
        full_URL = base_plus_endpoint_encoded(f'/v2/Reports/Session-Log?limit=10&startdate=2020-10-01&enddate=2020-10-03')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # these don't get affected by the level.
        r = response.json()
        response_info = r["report"]["responseInfo"]
        response_set = r["report"]["responseSet"]
        assert(response_info["count"] >= 1)

    def test01b_session_log_report_matchstr(self):
        # note api_key is required, but already in headers
        full_URL = base_plus_endpoint_encoded(f'/v2/Reports/Session-Log?limit=10&matchstr=/v2/Documents/Abstract')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # these don't get affected by the level.
        r = response.json()
        response_info = r["report"]["responseInfo"]
        response_set = r["report"]["responseSet"]
        assert(response_info["count"] >= 1)

    def test01b_session_log_report_download(self):
        # note api_key is required, but already in headers
        full_URL = base_plus_endpoint_encoded(f'/v2/Reports/Session-Log?limit=10&matchstr=/v2/Documents/Abstract&download=true')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # these don't get affected by the level.
        assert (response.headers["content-disposition"] == 'attachment; filename=vw_reports_session_activity.csv')

    def test02_document_view__log_report(self):
        # note api_key is required, but already in headers
        full_URL = base_plus_endpoint_encoded(f'/v2/Reports/Document-View-Log?limit=10&offset=5')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # these don't get affected by the level.
        r = response.json()
        response_info = r["report"]["responseInfo"]
        response_set = r["report"]["responseSet"]
        assert(response_info["count"] >= 1)

    def test03_document_view__stat_report(self):
        # note api_key is required, but already in headers
        full_URL = base_plus_endpoint_encoded(f'/v2/Reports/Document-View-Stat?limit=10')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # these don't get affected by the level.
        r = response.json()
        response_info = r["report"]["responseInfo"]
        response_set = r["report"]["responseSet"]
        assert(response_info["count"] >= 1)

    def test04_user_searches_report(self):
        # note api_key is required, but already in headers
        full_URL = base_plus_endpoint_encoded(f'/v2/Reports/User-Searches?limit=10')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # these don't get affected by the level.
        r = response.json()
        response_info = r["report"]["responseInfo"]
        response_set = r["report"]["responseSet"]
        assert(response_info["count"] >= 1)

if __name__ == '__main__':
    unittest.main()
    print ("Tests Complete.")