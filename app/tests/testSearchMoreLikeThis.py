#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Third-party imports...
#from nose.tools import assert_true

import sys
import os.path

folder = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
if folder == "tests": # testing from within WingIDE, default folder is tests
    sys.path.append('../libs')
    sys.path.append('../config')
    sys.path.append('../../app')
else: # python running from should be within folder app
    sys.path.append('./libs')
    sys.path.append('./config')

import unittest
import requests
from requests.utils import requote_uri
import urllib

from unitTestConfig import base_api, base_plus_endpoint_encoded, headers

class TestSearchMoreLikeThis(unittest.TestCase):
    def test_search_morelike_1a(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/SearchParagraphs/?sourcecode=AOP&paratext=mind&parascope=dreams&similarcount=4')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        r = response.json()
        # print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        print (f"Count: {response_info['count']}")
        assert(response_info["count"] == 2)
        try:
            length = len(response_set[0]["similarityMatch"]["similarDocs"]["AOP.016.0171A"])
        except KeyError:
            length = len(response_set[1]["similarityMatch"]["similarDocs"]["AOP.016.0171A"])            
            
        assert(length == 4)
        

if __name__ == '__main__':
    unittest.main()
