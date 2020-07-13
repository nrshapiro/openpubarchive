#!/usr/bin/env python
# -*- coding: utf-8 -*-
#2020.0610 # Upgraded tests to v2; set up tests against AOP which seems to be discontinued and thus constant

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

from unitTestConfig import base_api, base_plus_endpoint_encoded

class TestSearch(unittest.TestCase):
    def test_search_long_para(self):
        # This produces 0 results on the GVPi server; this result is correct though
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?sourcecode=AOP&paratext=physics%20science%20observations&abstract=True')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["count"] == 3)
        print (response_set)

    def test_search_long_para_alt_seems_to_show_solr_misses_one(self):
        # This produces 0 results on the GVPi server; this result is correct though
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?sourcecode=AOP&fulltext1="physics%20science%20observations"~90&abstract=True')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["count"] == 3) # should be 3.  I confirmed all three papers above in test_search_long_para...not sure why this fails.
        print (response_set)

    def test_0a_rank(self): 
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?sourcecode=AOP&fulltext1=cried&sort=rank&limit=15&offset=0')
        response = requests.get(full_URL)
        assert(response.ok == True) # rank is accepted, same as score
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] == 47)
        #print (response_set)
        for n in response_set:
            print (n["documentRef"])
        # Confirm that the request-response cycle completed successfully.
        
    def test_0b_parameter_error(self):
        # bad boolean parameter
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?viewperiod=&fulltext1=cried&sort=rank&synonyms=WTF')
        response = requests.get(full_URL)
        assert(response.ok == False)
        r = response.json()

    def test_0b_good_language_code(self):
        # bad boolean parameter
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?fulltext1=cried&sourcelangcode=en')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()

    def test_0b_bad_language_code(self):
        # bad boolean parameter
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?viewperiod=&fulltext1=cried&sourcelangcode=e')
        response = requests.get(full_URL)
        assert(response.ok == False)
        r = response.json()

    def test_1a_search_mixedcase(self):
        # Send a request to the API server and store the response.
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?author=Greenfield')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        #print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] >= 6)
        #print (response_set)
        for n in response_set:
            print (n["documentRef"])
        # Confirm that the request-response cycle completed successfully.

    def test_1b_search_lowercase(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?author=greenfield')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] >= 6)
        print (response_set[0])
        # Confirm that the request-response cycle completed successfully.

    def test_1c_search_wildcard(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?author=gre?nfield')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        # print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] >= 7)
        # print (response_set)
        # Confirm that the request-response cycle completed successfully.

    def test_search_journalcode(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?author=Bollas&sourcecode=AOP')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        # print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] == 2)
        print (response_set[0])

    def test_search_author_and_journalcode(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?author=Levin&sourcecode=AOP')
        response = requests.get(full_URL)
        r = response.json()
        assert(response.ok == True)
        # print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["count"] == 12)
        print (response_set[0])

    def test_search_author_and_journalcode_and_text(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?author=Blum&sourcecode=AOP&fulltext1=transference')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        # print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["count"] == 2)
        print (response_set[0])

    def test_search_author_and_journalcode_and_citecount(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?author=Bollas&sourcecode=AOP&citecount=2')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["count"] == 1)
        print (response_set[0])

    def test_search_startyear(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?sourcecode=aop&startyear=2015')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] == 20)
        print (response_set[0])

    def test_search_endyear(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?sourcecode=aop&endyear=2011') # note: no volume in 2009-2011
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] == 611)
        print (response_set[0])

    def test_search_year_range1(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?sourcecode=aop&startyear=1975&endyear=1976')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] == 42)
        print (response_set[0])

    def test_search_year_range2(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?sourcecode=aop&startyear=1975&endyear=1975')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] == 21)
        print (response_set[0])

    def test_search_year_range3(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?sourcecode=aop&startyear=1975&endyear=2020')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] == 589)
        print (response_set[0])

    def test_search_title(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?sourcecode=aop&title=west')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["fullCount"] == 3)
        print (response_set[0])

    def test_search_almost_all_params(self):
        full_URL = base_plus_endpoint_encoded('/v2/Database/Search/?paratext=transference&parascope=doc&sourcecode=aop&sourcetype=journal&sourcelangcode=EN&volume=10&author=blum&startyear=1982&facetfields=art_sourcetype')
        response = requests.get(full_URL)
        assert(response.ok == True)
        r = response.json()
        print (r)
        response_info = r["documentList"]["responseInfo"]
        response_set = r["documentList"]["responseSet"] 
        assert(response_info["count"] == 1)
        print (response_set[0])

if __name__ == '__main__':
    unittest.main()
    