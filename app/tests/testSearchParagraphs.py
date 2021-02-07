#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest
import requests
import opasConfig

from unitTestConfig import base_plus_endpoint_encoded, headers

class TestSearchParagraphs(unittest.TestCase):
    def test_search_para_1a(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/SearchParagraphs/?sourcecode=AOP&paratext=disorder and mind')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        r = response.json()
        # print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        print (f"Count: {response_info['count']}")
        assert(response_info["count"] >= 11) 
        # print (response_set[0])

    def test_search_para_2a(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/SearchParagraphs/?sourcecode=AOP&paratext=disorderly mind')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        r = response.json()
        # print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        print (f"Count: {response_info['count']}")
        if opasConfig.PARATEXT_SEARCH_METHOD:
            assert(response_info["count"] == 1)
        else:
            assert(response_info["count"] >= 11)
        # print (response_set[0])

    def test_search_para_2b(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/SearchParagraphs/?sourcecode=AOP&paratext=disorderly and mind')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        r = response.json()
        # print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        print (f"Count: {response_info['count']}")
        if opasConfig.PARATEXT_SEARCH_METHOD:
            assert(response_info["count"] >= 5)
        else:
            assert(response_info["count"] >= 5)
        # print (response_set[0])

    def test_search_para_3(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/SearchParagraphs/?sourcecode=AOP&paratext=mind&parascope=dreams')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        r = response.json()
        # print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        print (f"Count: {response_info['count']}")
        assert(response_info["count"] == 2)
        # print (response_set[0])

    def test_search_para_3b(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/SearchParagraphs/?sourcecode=AOP&paratext=mind&parascope=dreams&similarcount=4')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        r = response.json()
        # print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        print (f"Count: {response_info['count']}")
        assert(response_info["count"] == 2)


if __name__ == '__main__':
    unittest.main()
