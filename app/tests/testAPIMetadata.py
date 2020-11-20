#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Updates:
#  2020-04-06 - Testing tightened to be exact.
#  2020-04-30 - Added test 8x to test source info retrieval with wildcards

import unittest
import requests
import unitTestConfig
from unitTestConfig import base_plus_endpoint_encoded, headers

# import opasCentralDBLib

class TestMetadata(unittest.TestCase):
    """
    Note: tests are performed in alphabetical order, hence the function naming
          with forced order in the names.
    """   

    #def test_0_meta_volumes_db(self):
        ## New method to bring back lists of volumes, including all, or all of one type, or all of one type and code.
        #ocd = opasCentralDBLib.opasCentralDB()
        #count, vols = ocd.get_volumes(source_code=None, source_type=None)
        #print (f"DB All Vols Count {count}")
        #assert(count >= unitTestConfig.VOL_COUNT_ALL_VOLUMES)
        
        ## ---------------------------------------------------------------------------------------
        #source_type = "book"
        #source_code = None       
        #count, vols = ocd.get_volumes(source_code=source_code, source_type=source_type)
        #print (f"DB {source_type} Vol Count {count}")
        #assert(count >= unitTestConfig.VOL_COUNT_ALL_BOOKS)
        ## ---------------------------------------------------------------------------------------
        #source_type = "book"
        #source_code = "GW"
        #count, vols = ocd.get_volumes(source_code=source_code, source_type=source_type)
        #print (f"DB {source_type} {source_code} Vol Count {count}")
        #assert(count >= unitTestConfig.VOL_COUNT_GW)
        ## ---------------------------------------------------------------------------------------
        #source_type = "journal"
        #source_code = None
        #count, vols = ocd.get_volumes(source_code=source_code, source_type=source_type)
        #print (f"DB {source_type} Vol Count {count}")
        #assert(count >= unitTestConfig.VOL_COUNT_ALL_JOURNALS)
        ## ---------------------------------------------------------------------------------------
        #source_type = "journal"
        #source_code = "IJPSP"
        #count, vols = ocd.get_volumes(source_code=source_code, source_type=source_type)
        #print (f"DB {source_type} {source_code} Vol Count {count}")
        #assert(count == unitTestConfig.VOL_COUNT_IJPSP)
        ## ---------------------------------------------------------------------------------------
        #source_type = "videostream"
        #source_code = None
        #count, vols = ocd.get_volumes(source_code=source_code, source_type=source_type)
        #print (f"DB {source_type} Vol Count {count}")
        #assert(count >= unitTestConfig.VOL_COUNT_VIDEOS)
        ## ---------------------------------------------------------------------------------------
        #source_type = "videostream"
        #source_code = "PEPVS"
        #count, vols = ocd.get_volumes(source_code=source_code, source_type=source_type)
        #print (f"DB {source_type} {source_code} Vol Count {count}")
        #assert(count >= unitTestConfig.VOL_COUNT_VIDEOS_PEPVS)
        
    def test_0_meta_volumes_api_book(self): 
        # ---------------------------------------------------------------------------------------
        # Version 2 style, better, including sourcetype support
        # ---------------------------------------------------------------------------------------
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/?sourcetype=book') 
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print (f"Book Count: {r['volumeList']['responseInfo']['fullCount']}")
        assert(r['volumeList']['responseInfo']['fullCount'] >= unitTestConfig.VOL_COUNT_ALL_BOOKS) 

    def test_0_meta_volumes_api_journal(self): 
        # ---------------------------------------------------------------------------------------
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/?sourcetype=journal') #  all journals
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print (f"Journal Vol Count: {r['volumeList']['responseInfo']['fullCount']}")
        assert(r['volumeList']['responseInfo']['fullCount'] >= unitTestConfig.VOL_COUNT_ALL_JOURNALS) 

    def test_0_meta_volumes_api_videostream(self): 
        # ---------------------------------------------------------------------------------------
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/?sourcetype=videostream') #  all videos
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print (f"Video Source Count: {r['volumeList']['responseInfo']['fullCount']}")
        assert(r['volumeList']['responseInfo']['fullCount'] == unitTestConfig.VOL_COUNT_VIDEOS)

    def test_0_meta_volumes_api_ZBK(self): 
        # ---------------------------------------------------------------------------------------
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/?sourcecode=ZBK')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print (f"ZBK Volume Count: {r['volumeList']['responseInfo']['fullCount']}")
        assert(r['volumeList']['responseInfo']['fullCount'] >= unitTestConfig.VOL_COUNT_ZBK) 

    def test_0_meta_volumes_api_IJPSP(self): 
        # ---------------------------------------------------------------------------------------
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/?sourcecode=IJPSP')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        assert(r['volumeList']['responseInfo']['fullCount'] == unitTestConfig.VOL_COUNT_IJPSP) # 11

    def test_0_meta_volumes_api_GW(self): 
        # ---------------------------------------------------------------------------------------
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/?sourcecode=GW')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print (f"GW Volume Count: {r['volumeList']['responseInfo']['fullCount']}")
        assert(r['volumeList']['responseInfo']['fullCount'] == unitTestConfig.VOL_COUNT_GW) # 18 vols of GW

    def test_0_meta_volumes_api_SE(self): 
        # ---------------------------------------------------------------------------------------
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/?sourcecode=SE')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print (f"SE Volume Count: {r['volumeList']['responseInfo']['fullCount']}")
        assert(r['volumeList']['responseInfo']['fullCount'] == unitTestConfig.VOL_COUNT_SE + 1) # 24 vols of SE + new overview vol 0

    def test_0_meta_volumes_api_IPL(self): 
        # ---------------------------------------------------------------------------------------
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/?sourcecode=IPL')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print (f"IPL Volume Count: {r['volumeList']['responseInfo']['fullCount']}")
        assert(r['volumeList']['responseInfo']['fullCount'] == unitTestConfig.VOL_COUNT_IPL) # 22 vols of IPL

    def test_0_meta_volumes_api_NLP(self): 
        # ---------------------------------------------------------------------------------------
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/?sourcecode=NLP')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print (f"IPL Volume Count: {r['volumeList']['responseInfo']['fullCount']}")
        assert(r['volumeList']['responseInfo']['fullCount'] == unitTestConfig.VOL_COUNT_NLP) # 22 vols of IPL


    def test_0_meta_volumes_api_error(self): 
        # ---------------------------------------------------------------------------------------
        # try an error
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/?sourcecode=IJPNOT')
        response = requests.get(full_URL, headers=headers)
        assert(response.status_code == 400)
        r = response.json()
        assert(r["detail"] == "Failure: Bad SourceCode IJPNOT")

    def test_0_meta_volumes_api_ALL(self): 
        # ---------------------------------------------------------------------------------------
        # all journals and videos 
        # (books not included, ***perhaps this option should not exist since it seems inconsistent ***.)
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Volumes/') 
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        assert(r['volumeList']['responseInfo']['fullCount'] >= unitTestConfig.VOL_COUNT_ALL_VOLUMES) # count of journal and video volumes
        

    def test_1_meta_contents_for_source(self):
        """
        Journal Content Lists for a source
        /v1/Metadata/Contents/{SourceCode}/
        """
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Contents/BJP/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print(r['documentList']['responseInfo']['fullCount']) # 2735
        assert(r['documentList']['responseInfo']['fullCount'] >= unitTestConfig.ARTICLE_COUNT_BJP)
        # print ("test_metadata_journals complete.")
       
    def test_1B_meta_contents_for_source(self):
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Contents/FA/14/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print(r['documentList']['responseInfo']['fullCount']) 
        # print ("test_metadata_journals complete.")
        # Check this TOC items
        assert(r['documentList']['responseSet'][6]["documentID"] == "FA.014A.0104A")
        assert(r['documentList']['responseSet'][6]["issueTitle"] == "No. 64")
        assert(r['documentList']['responseSet'][6]["issueSeqNbr"] == "64")
        assert(r['documentList']['responseSet'][6]["pgStart"] == "104")
        
        
    def test_2_meta_contents_source_volume(self):
        """
        Journal Content Lists for a source and vol
        ​/v1​/Metadata​/Contents​/{SourceCode}​/{SourceVolume}​/
        """
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Contents/BJP/1/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        assert(r['documentList']['responseInfo']['fullCount'] == unitTestConfig.ARTICLE_COUNT_VOL1_BJP)

        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Contents/IJP/1/?limit=1')
        # Confirm that the request-response cycle completed successfully.
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        r = response.json()
        assert(r['documentList']['responseSet'][0]['documentID'] == 'IJP.001.0001A')
        assert(r['documentList']['responseSet'][0]['pgRg'] == '1-2')

    def test_3_meta_video_sources(self):
        """
        List of video sources (not individual videos, EXCEPT if specified by parameter)
        /v1/Metadata/Videos/
        """
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Videos/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print(r['sourceInfo']['responseInfo']['fullCount']) 
        assert(r['sourceInfo']['responseInfo']['fullCount'] == unitTestConfig.VIDEOSOURCECOUNT)

        # try with src code parameter
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Videos/?SourceCode=AFCVS&limit=1')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        assert(r['sourceInfo']['responseSet'][0]['title'] == 'Anna Freud Center Video Collection')

    def test_3B_meta_videostreams(self):
        """
        List of video sources (not individual videos, EXCEPT if specified by parameter)
        /v1/Metadata/Videos/
        """
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Videos/?streams=False')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print(r['sourceInfo']['responseInfo']['fullCount']) 
        assert(r['sourceInfo']['responseInfo']['fullCount'] == unitTestConfig.VIDEOCOUNT)

        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Videos/?streams=True')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print(r['sourceInfo']['responseInfo']['fullCount']) 
        assert(r['sourceInfo']['responseInfo']['fullCount'] == unitTestConfig.VIDEOSOURCECOUNT)

        # test default streams parameter (which is streams=True)
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Videos/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print(r['sourceInfo']['responseInfo']['fullCount']) 
        assert(r['sourceInfo']['responseInfo']['fullCount'] == unitTestConfig.VIDEOSOURCECOUNT)

    def test_6_meta_book_names(self):
        """
        List of book names
        /v2/Metadata/Books/
        """
        full_URL = base_plus_endpoint_encoded('/v2/Metadata/Books/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        print (f"Book Count: {r['sourceInfo']['responseInfo']['fullCount']}")
        assert(r['sourceInfo']['responseInfo']['fullCount'] >= unitTestConfig.BOOKCOUNT)

    def test_7_meta_get_sourcenames(self):
        """
        List of names for a specific source
        /v2/Metadata/{SourceType}/{SourceCode}/
        """
        full_URL = base_plus_endpoint_encoded('/v1/Metadata/Journals/IJPSP/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        assert(r['sourceInfo']['responseInfo']['fullCount'] == 1)
        assert(r['sourceInfo']['responseSet'][0]['displayTitle'] == 'International Journal of Psychoanalytic Self Psychology')
        
    def test_8_meta_all_sources(self):
        """
        List of names for a specific source
        /v2/Metadata/{SourceType}/{SourceCode}/
        """
        full_URL = base_plus_endpoint_encoded('/v1/Metadata/*/*/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        count = r['sourceInfo']['responseInfo']['count']
        print (f"Count {count}")
        assert(count >= unitTestConfig.ALL_SOURCES_COUNT)

    def test_8b_meta_all_sources(self):
        """
        List of names for a specific source
        /v2/Metadata/{SourceType}/{SourceCode}/
        """
        full_URL = base_plus_endpoint_encoded('/v1/Metadata/*/IJP/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        assert(r['sourceInfo']['responseInfo']['count'] == 1)
    
    def test_8b2_meta_all_sources(self):
        """
        List of names for a specific source, a book, but not spec'd as book
        /v2/Metadata/{SourceType}/{SourceCode}/
        """
        # get all the PEP Codes
        full_URL = base_plus_endpoint_encoded('/v1/Metadata/*/*/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        pep_codes = []
        for n in r['sourceInfo']['responseSet']:
            pep_codes.append(n['PEPCode'])
        # Now test to make sure they can be read (if there's missing data in the product table, can cause error)
        for n in pep_codes:
            full_URL = base_plus_endpoint_encoded(f'/v2/Metadata/*/{n}/')
            # Confirm that the request-response cycle completed successfully.
            assert(response.ok == True)
            # test return
            r = response.json()
            print(f"{n} count={r['sourceInfo']['responseInfo']['count']}")
            assert(r['sourceInfo']['responseInfo']['count'] >= 1)

    def test_8b3_meta_sourcename(self):
        """
        List of names for a specific source by name
        /v2/Metadata/{SourceType}/{SourceCode}/
        """
        full_URL = base_plus_endpoint_encoded('/v1/Metadata/*/*/?sourcename=.*psychoanalytic.*')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        assert(r['sourceInfo']['responseInfo']['count'] == 33)

        full_URL = base_plus_endpoint_encoded('/v1/Metadata/*/*/?sourcename=.*international journal of psychoanalysis.*')
        response = requests.get(full_URL, headers=headers)
        # Confirm that the request-response cycle completed successfully.
        assert(response.ok == True)
        # test return
        r = response.json()
        assert(r['sourceInfo']['responseInfo']['count'] == 4)

    def test_8c_meta_all_sources_nonsense(self):
        """
        List of names for a source that doesn't match the type
        /v1/Metadata/{SourceType}/{SourceCode}/
        """
        full_URL = base_plus_endpoint_encoded('/v1/Metadata/Books/IJP/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == True)
        # test return
        r = response.json()
        assert(r['sourceInfo']['responseInfo']['count'] == 0)
    
    def test_8d_meta_all_sourcetype_nonsense(self):
        """
        List of names for a source for an unknown type
        /v1/Metadata/{SourceType}/{SourceCode}/
        
        Currently: just changes to Journal, maybe should change to "*"
        """
        full_URL = base_plus_endpoint_encoded('/v1/Metadata/Garbage/*/')
        response = requests.get(full_URL, headers=headers)
        assert(response.ok == False)
        
        full_URL = base_plus_endpoint_encoded('/v1/Metadata/Garbage/IJP/')
        response = requests.get(full_URL, headers=headers)
        # Confirm that the request-response cycle completed successfully.
        assert(response.ok == False)
        
        full_URL = base_plus_endpoint_encoded('/v1/Metadata/Garbage/GW/')
        response = requests.get(full_URL, headers=headers)
        # Confirm that the request-response cycle completed successfully.
        assert(response.ok == False)
        
if __name__ == '__main__':
    unittest.main()
    print ("Tests Complete.")