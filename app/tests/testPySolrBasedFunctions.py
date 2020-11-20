#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest
import opasAPISupportLib
import opasConfig
import opasQueryHelper
import opasCentralDBLib
import opasPySolrLib
import models

from unitTestConfig import base_api, base_plus_endpoint_encoded, headers
ocd = opasCentralDBLib.opasCentralDB()

class TestPySolrBasedFunctions(unittest.TestCase):
    """
    Tests
    
    Note: tests are performed in alphabetical order, hence the function naming
          with forced order in the names.
    
    """
   
    def test_1_metadata_get_videos(self):
        """
        Test
          1) list of video returns for metadata_get_videos
          2) List of sources by type
          3) 
        """
        data = opasPySolrLib.metadata_get_videos(src_type="Videos", pep_code=None, limit=opasConfig.DEFAULT_LIMIT_FOR_METADATA_LISTS, offset=0)
        # Confirm that the request-response cycle completed successfully.
        # check to make sure a known value is among the data returned
        dataList = [d['documentID'] for d in data[1] if 'documentID' in d]
        assert ('IPSAVS.001A.0001A' in dataList)
        data = opasAPISupportLib.metadata_get_source_info(src_type="journal")
        dataList = [d.PEPCode for d in data.sourceInfo.responseSet]
        assert ('PAQ' in dataList)
        data = opasAPISupportLib.metadata_get_source_info(src_type="book")
        dataList = [d.PEPCode for d in data.sourceInfo.responseSet]
        assert ('ZBK075' in dataList)      

    def test_2_get_vols(self):
        data = opasPySolrLib.metadata_get_volumes(source_type="journal")
        len(data)
        
if __name__ == '__main__':
    unittest.main()
    print ("Tests Complete.")