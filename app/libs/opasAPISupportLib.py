#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=C0321,C0103,C0301,E1101,C0303,E1004,C0330,R0915,R0914,W0703,C0326
# doctest_ellipsis.py

"""
opasAPISupportLib

This library is meant to hold the 'meat' of the API based Solr queries and other support 
functions to keep the FastAPI definitions smaller, easier to read, and more manageable.

Also, some of these functions are reused in different API calls.

#TODO: Should switch back to using pysolr, rather than solrpy.  solrpy is not being maintained
       and pysolr has leapfrogged it (and now works for secured Solr installs).

"""
#Revision Notes:
    #2019.0614.1 - Python 3.7 compatible.  Work in progress.
    #2019.1203.1 - fixed authentication value error in show abstract call
    #2019.1222.1 - Finished term_count_list function for endpoint termcounts
    #2020.0224.1 - Added biblioxml
    #2020.0226.1 - Support TOC instance as exception for abstracting extraction (extract_abstract_from_html)
                # Python 3 only now
    #2020.0401.1 - Set it so user-agent is optional in session settings, in case client doesn't supply it (as PaDS didn't)
    #2020.0423.1 - database_get_most_cited fixes, confusion between publication_period, and period, sorted.
    #2020.0426.1 - Doc level testing of functions and doctest cleanup...
                # setting doctests so they pass even though the data varies in the DB
                # all tests now pass at least with a full database load.
                # Note: ellipses in doctest now working, see configuration in main and in doctests, 
                # e.g., document_get_info (line 417) and database_get_most_viewed (line 525)
    #2020.0505.1 Removed redundant param document_type from database_get_most_viewed (source_type already there)

    #2020.0530.1 Updated getmostviewed routine and all support for it to use the new in place updated art_view count fields in Solr
                # rather than using the values from the database, as before.  Moving the data to Solr allows these values to be
                # integrated with a solr query.

__author__      = "Neil R. Shapiro"
__copyright__   = "Copyright 2020, Psychoanalytic Electronic Publishing"
__license__     = "Apache 2.0"
__version__     = "2020.0601.1"
__status__      = "Development"

import os
import os.path
# from xml.sax import SAXParseException
import sys
# import shlex
import copy
import string

sys.path.append('./solrpy')
sys.path.append('./libs/configLib')

# print(os.getcwd())
import http.cookies
import re
import secrets
import socket, struct
from collections import OrderedDict
from urllib.parse import unquote
import json
from xml.sax import SAXParseException

from starlette.responses import JSONResponse, Response
from starlette.requests import Request
from starlette.responses import Response
import starlette.status as httpCodes

#from starlette.status import HTTP_200_OK, \
                                #HTTP_400_BAD_REQUEST, \
                                #HTTP_401_UNAUTHORIZED, \
                                #HTTP_403_FORBIDDEN, \
                                #HTTP_404_NOT_FOUND, \
                                #HTTP_500_INTERNAL_SERVER_ERROR, \
                                #HTTP_503_SERVICE_UNAVAILABLE
import time
# used this name because later we needed to refer to the module, and datetime is also the name
#  of the import from datetime.
import datetime as dtime 
# import datetime
from datetime import datetime
# from typing import Union, Optional, Tuple, List
# from enum import Enum
# import pymysql
# import s3fs # read s3 files just like local files (with keys)

import opasConfig
import localsecrets
from localsecrets import CLIENT_DB

import opasFileSupport
# opas_fs = opasFileSupport.FlexFileSystem(key=localsecrets.S3_KEY, secret=localsecrets.S3_SECRET)

from localsecrets import BASEURL, SOLRURL, SOLRUSER, SOLRPW, DEBUG_DOCUMENTS, SOLR_DEBUG, CONFIG, COOKIE_DOMAIN
from localsecrets import TIME_FORMAT_STR

# from opasConfig import OPASSESSIONID
# import configLib.opasCoreConfig as opasCoreConfig
from stdMessageLib import COPYRIGHT_PAGE_HTML  # copyright page text to be inserted in ePubs and PDFs
from configLib.opasCoreConfig import solr_docs, solr_authors, solr_gloss, solr_docs_term_search, solr_authors_term_search
from configLib.opasCoreConfig import solr_docs2, solr_authors2, solr_gloss2

from configLib.opasCoreConfig import EXTENDED_CORES

# from fastapi import HTTPException

# Removed support for Py2, only Py3 supported now
pyVer = 3
from io import StringIO
import solrpy as solr
import lxml
import logging
logger = logging.getLogger(__name__)

from lxml import etree
# from pydantic import BaseModel
from pydantic import ValidationError

# from ebooklib import epub              # for HTML 2 EPUB conversion
from xhtml2pdf import pisa             # for HTML 2 PDF conversion

# note: documents and documentList share the same internals, except the first level json label (documents vs documentlist)
import models

import opasXMLHelper as opasxmllib
import opasQueryHelper
import opasGenSupportLib as opasgenlib
import opasCentralDBLib
import schemaMap
import opasDocPermissions as opasDocPerm
import opasPySolrLib
from opasPySolrLib import search_text, search_text_qs

# count_anchors = 0

def has_data(str):
    ret_val = True
    if str is None or str == "":
        ret_val = False

    return ret_val

def get_query_item_of_interest(solrQuery):
    """
    Give a solrQuery, use that to derive a string to be logged in the endpoint_session
      record column item_of_interest
    """
    ret_val = None
    try:
        try:
            fq = re.sub("art_level:1(\s\&\&\s)?", "", solrQuery.filterQ, re.I)
            if fq != '':
                ret_val = f"f:'{fq}'"
                spacer = " "
            else:
                ret_val = ""
                spacer = ""
        except:
            fq = ""
            ret_val = ""
            spacer = ""
    
        try:
            q = re.sub("\*:\*|{!parent\swhich=\'art_level:1\'}\sart_level:2\s&&\s", "", solrQuery.searchQ, re.I)
            if q != '':
                col_width_remaining = opasConfig.DB_ITEM_OF_INTEREST_WIDTH - len(fq) # don't exceed column width for logging 
                ret_val += f"{spacer}q:'{q[:col_width_remaining]}'"
        except Exception as e:
            pass
    except:
        ret_val = None

    return ret_val

def remove_leading_zeros(numeric_string):
    """
        >>> remove_leading_zeros("0033")
        '33'
        
    """
    ret_val = ""
    for n in numeric_string:
        if n != "0":
            ret_val += n
    
    return ret_val
            
def split_article_id(article_id):
    """
    >>> split_article_id("gap.005.0199a")
    ('GAP', None, '5', '199A', None)

    >>> split_article_id("rfp.075.0017a")
    ('RFP', None, '75', '17A', None)

    >>> split_article_id(None)
    (None, None, None, None, None)

    """
    journal = year = vol = page = page_id = None
    if article_id is not None:
        article_id = article_id.upper()
        
        try:
            journal, vol, page = article_id.split(".")
        except Exception as e:
            try:
                a,b,c,d = article_id.split(".")
                if d[0] == "P":
                    journal, vol, page, page_id = a, b, c, d
                elif b[:2] in [19, 20]:
                    journal, year, vol, page = a, b, c, d
            except Exception as e:
                logger.error(f"Split Article ID error: can not split ID {article_id} ({e})")
        else:
            vol = remove_leading_zeros(vol)
            page = remove_leading_zeros(page)
        
            if journal is not None:
                journal = journal.upper()
        
            if year is not None:
                year = page.upper()
                
            if page is not None:
                page = page.upper()
                
            if page_id is not None:
                page_id = page_id.upper()
       
    return journal, year, vol, page, page_id
    
#-----------------------------------------------------------------------------
def get_basecode(document_id):
    """
    Get basecode from document_id
    """
    ret_val = None
    try:
        parts = document_id.split(".")
        ret_val = parts[0]
    except Exception as e:
        logger.error(f"Bad document_id {document_id} to get_basecode. {e}")

    #TODO: later we might want to check for special book basecodes.

    return ret_val
#-----------------------------------------------------------------------------
def get_max_age(keep_active=False):
    if keep_active:    
        ret_val = opasConfig.COOKIE_MAX_KEEP_TIME    
    else:
        ret_val = opasConfig.COOKIE_MIN_KEEP_TIME     
    return ret_val  # maxAge


#-----------------------------------------------------------------------------
def get_session_info(request: Request,
                     response: Response,
                     session_id:str=None, 
                     client_id=None,
                     expires_time=None, 
                     force_new_session=False,
                     user=None):
    """
    Return a sessionInfo object with all of that info, and a database handle

    Get session info accesses the DB per the session_id to see if the session exists.

     1) If no session_id is supplied (None), it returns a default SessionInfo object, user not logged in,
        with a session id constant defined in opasConfig.NO_SESSION_ID.  These should
        not be written to the DB api_session table (watch elsewhere).

     2) If there is a session_id, it gets the session_info from the api_sessions table in the DB.
        a) If it's not there (None):
           i) It does a permission check on the user via the session_id
           ii) It saves the session
        b) If it's there already: (Repeatable, quickest path)
           i) Done, returns it.  No update.  
    """
    ocd = opasCentralDBLib.opasCentralDB()
    if session_id is not None and session_id != opasConfig.NO_SESSION_ID:
        ts = time.time()
        session_info = ocd.get_session_from_db(session_id)
        if session_info is None:
            if client_id is None or client_id == 0 or client_id == opasConfig.NO_CLIENT_ID:
                logger.info(f"get_session_info called by {inspect.stack()[1].function}, with no client_id")
                raise httpCodes.HTTPException(status_code=400, detail="Must have a valid client-id")
            else:
                logger.info(f"Session {session_id} not found.  Getting from authserver (will save on server)")
                session_info = opasDocPerm.get_authserver_session_info(session_id=session_id, client_id=client_id)
        else:
            logger.debug(f"Session {session_id} found in DB.  Checking if already marked authenticated.")
            if session_info.authenticated == 0: # not logged in
                # better check if now they are logged in
                logger.info(f"User was not logged in; checking to see if they are now.")
                session_info = opasDocPerm.get_authserver_session_info(session_id=session_id, client_id=client_id)
            else:
                logger.debug(f"User was logged in.  No further checks needed.")

        if opasConfig.LOG_CALL_TIMING:
            logger.debug(f"Get/Save session info response time: {time.time() - ts}")
        
        logger.info("getSessionInfo: %s", session_info)
        
    else:
        logger.debug("No SessionID; Default session info returned (Not Logged In)")
        session_info = models.SessionInfo() # default session model

    return ocd, session_info

#-----------------------------------------------------------------------------
def extract_abstract_from_html(html_str, xpath_to_extract=opasConfig.HTML_XPATH_ABSTRACT): # xpath example: "//div[@id='abs']"
    # parse HTML
    htree = etree.HTML(html_str)
    ret_val = htree.xpath(xpath_to_extract)
    # TOC's should be passed through "whole" (well, just the body, since headers will be added.)
    if ret_val == []: # see if it's a TOC
        ret_val = htree.xpath(opasConfig.HTML_XPATH_TOC_INSTANCE) # e.g, "//div[@data-arttype='TOC']"
        if ret_val != []:
            ret_val = htree.xpath(opasConfig.HTML_XPATH_DOC_BODY) # e.g., "//div[@class='body']"
    # make sure it's a string
    ret_val = opasQueryHelper.force_string_return_from_various_return_types(ret_val)

    return ret_val

#-----------------------------------------------------------------------------
#def get_session_id(request):
    ## this will be a sesson ID from the client--must be in every call!
    #ret_val = request.cookies.get(opasConfig.OPASSESSIONID, None)
    #if ret_val is None:
        #ret_val = request.headers.get(opasConfig.CLIENTSESSIONID, None)

    #return ret_val
#-----------------------------------------------------------------------------
#def get_access_token(request):
    #ret_val = request.cookies.get(opasConfig.OPASACCESSTOKEN, None)
    #return ret_val

#-----------------------------------------------------------------------------
def get_expiration_time(request):
    ret_val = request.cookies.get(opasConfig.OPASEXPIRES, None)
    return ret_val
#-----------------------------------------------------------------------------
def check_solr_docs_connection():
    """
    Queries the solrDocs core (i.e., pepwebdocs) to see if the server is up and running.
    Solr also supports a ping, at the corename + "/ping", but that doesn't work through pysolr as far as I can tell,
    so it was more straightforward to just query the Core. 

    Note that this only checks one core, since it's only checking if the Solr server is running.

    >>> check_solr_docs_connection()
    True

    """
    if solr_docs is None:
        return False
    else:
        try:
            results = solr_docs.query(q = "art_id:{}".format("APA.009.0331A"),  fields = "art_id, art_vol, art_year")
        except Exception as e:
            logger.error("Solr Connection Error: {}".format(e))
            return False
        else:
            if len(results.results) == 0:
                return False
        return True


##-----------------------------------------------------------------------------
#def document_get_info(document_id, fields="art_id, art_sourcetype, art_year, file_classification, art_sourcecode"):
    #"""
    #Gets key information about a single document for the specified fields.

    #>>> document_get_info('PEPGRANTVS.001.0003A', fields='file_classification')
    #{'file_classification': 'free', 'score': ...}

    #"""
    #ret_val = {}
    #if solr_docs is not None:
        #try:
            ## PEP indexes field in upper case, but just in case caller sends lower case, convert.
            #document_id = document_id.upper()
            #q_str = f"art_id:{document_id}"
            #logger.info(f"Solr Query: q={q_str}")
            #results = solr_docs.query(q = q_str, fields = fields)
        #except Exception as e:
            #logger.error(f"Solr Retrieval Error: {e}")
        #else:
            #if len(results.results) == 0:
                #return ret_val
            #else:
                #try:
                    #ret_val = results.results[0]
                #except Exception as e:
                    #logger.error(f"Solr Result Error: {e}")

    #return ret_val


#-----------------------------------------------------------------------------
def database_get_most_viewed( publication_period: int=5,
                              author: str=None,
                              title: str=None,
                              source_name: str=None,  
                              source_code: str=None,
                              source_type: str="journal",
                              abstract_requested: bool=False, 
                              view_period: int=4,      # 4=last12months default
                              view_count: str="1",        # up this later
                              req_url: str=None,
                              stat:bool=False, 
                              limit: int=5,           # Get top 10 from the period
                              offset=0,
                              mlt_count:int=None,
                              sort:str=None,
                              download=False, 
                              session_info=None
                            ):
    """
    Return the most viewed journal articles (often referred to as most downloaded) duing the prior period years.

    This is used for the statistical summary function and accesses only the relational database, not full-text Solr.

    Args:
        publication_period (int, optional): Look only at articles this many years back to current.  Defaults to 5.
        author (str, optional): Filter, include matching author names per string .  Defaults to None (no filter).
        title (str, optional): Filter, include only titles that match.  Defaults to None (no filter).
        source_name (str, optional): Filter, include only journals matching this name.  Defaults to None (no filter).
        source_type (str, optional): journals, books, or videostreams.
        view_period (int, optional): defaults to last12months

            view_period = { 0: "lastcalyear",
                            1: "lastweek",
                            2: "last1mos",
                            3: "last6mos",
                            4: "last12mos",
                           }

        limit (int, optional): Paging mechanism, return is limited to this number of items.
        offset (int, optional): Paging mechanism, start with this item in limited return set, 0 is first item.

    Returns:
        models.DocumentList: Pydantic structure (dict) for DocumentList.  See models.py

    Docstring Tests:

    >>> result, status = database_get_most_viewed()
    >>> result.documentList.responseSet[0].documentID if result.documentList.responseInfo.count >0 else "No views yet."
    '...'

    """
    ret_val = None
    ret_status = (200, "OK") # default is like HTTP_200_OK
    period = opasConfig.VALS_VIEWPERIODDICT_SOLRFIELDS.get(view_period, "last12mos")
    
    if sort is None:
        sort = f"{period} desc"

    start_year = dtime.date.today().year
    if publication_period is None:
        start_year = None
    else:
        start_year -= publication_period
        start_year = f">{start_year}"

    if stat:
        field_set = "STAT"
    else:
        field_set = None
        
    solr_query_spec = \
        opasQueryHelper.parse_search_query_parameters( viewperiod=view_period,
                                                       viewcount=view_count, 
                                                       source_name=source_name,
                                                       source_code=source_code,
                                                       source_type=source_type,
                                                       author=author,
                                                       title=title,
                                                       startyear=start_year,
                                                       highlightlimit=0, 
                                                       abstract_requested=abstract_requested,
                                                       return_field_set=field_set, 
                                                       sort = sort,
                                                       req_url = req_url
                                                       )
    if download: # much more limited document list if download==True
        ret_val, ret_status = opasPySolrLib.search_stats_for_download(solr_query_spec, 
                                                                      session_info=session_info
                                                                      )
    else:
        try:
            ret_val, ret_status = opasPySolrLib.search_text_qs(solr_query_spec, 
                                                               limit=limit,
                                                               offset=offset,
                                                               req_url = req_url, 
                                                               session_info=session_info
                                                              )
        except Exception as e:
            logger.warning(f"Search error {e}")

    return ret_val, ret_status   

#-----------------------------------------------------------------------------
def database_get_most_cited( publication_period: int=None,   # Limit the considered pubs to only those published in these years
                             cited_in_period: str='5',  # 
                             cite_count: int=0,              # Has to be cited more than this number of times, a large nbr speeds the query
                             author: str=None,
                             title: str=None,
                             source_name: str=None,  
                             source_code: str=None,
                             source_type: str=None,
                             abstract_requested: bool=True, 
                             req_url: str=None, 
                             stat:bool=False, 
                             limit: int=None,
                             offset: int=0,
                             mlt_count:int=None, 
                             sort:str=None,
                             download:bool=None, 
                             session_info=None
                             ):
    """
    Return the most cited journal articles duing the prior period years.

    period must be either '5', 10, '20', or 'all'

    args:
      limit: the number of records you want to return
      more_than: setting more_than to a large number speeds the query because the set to be sorted is smaller.
                 just set it so it's not so high you still get "limit" records back.

    >>> result, status = database_get_most_cited()
    >>> len(result.documentList.responseSet)>=10
    True

    """
    ret_val = {}
    ret_status = (200, "OK") # default is like HTTP_200_OK
    
    cited_in_period = opasConfig.normalize_val(cited_in_period, opasConfig.VALS_YEAROPTIONS, default='5')
    #if str(period).lower() not in models.TimePeriod._value2member_map_:
        #period = '5'

    if sort is None:
        sort = f"art_cited_{cited_in_period} desc"

    start_year = dtime.date.today().year
    if publication_period is None:
        start_year = None
    else:
        start_year -= publication_period
        start_year = f">{start_year}"

    cite_count_predicate = f"{cite_count} in {cited_in_period}"
    if stat:
        field_set = "STAT"
    else:
        field_set = None
    
    solr_query_spec = \
        opasQueryHelper.parse_search_query_parameters(citecount=cite_count_predicate, 
                                                      source_name=source_name,
                                                      source_code=source_code,
                                                      source_type=source_type, 
                                                      author=author,
                                                      title=title,
                                                      startyear=start_year,
                                                      highlightlimit=0, 
                                                      return_field_set=field_set, 
                                                      abstract_requested=abstract_requested,
                                                      similar_count=mlt_count, 
                                                      sort = sort,
                                                      req_url = req_url
                                                    )

    if download: # much more limited document list if download==True
        ret_val, ret_status = opasPySolrLib.search_stats_for_download(solr_query_spec, 
                                                                      session_info=session_info
                                                                     )
    else:
        try:
            ret_val, ret_status = opasPySolrLib.search_text_qs(solr_query_spec, 
                                                               limit=limit,
                                                               offset=offset,
                                                               #mlt_count=mlt_count, 
                                                               session_info=session_info, 
                                                               req_url = req_url
                                                              )
        except Exception as e:
            logger.warning(f"Search error {e}")
        
    return ret_val, ret_status   

#-----------------------------------------------------------------------------
def database_who_cited( publication_period: int=None,   # Limit the considered pubs to only those published in these years
                        cited_in_period: str='5',  # 
                        cited_art_id: str=None, # search rx for this
                        author: str=None,
                        title: str=None,
                        source_name: str=None,  
                        source_code: str=None,
                        source_type: str=None,
                        abstract_requested: bool=True, 
                        req_url: str=None, 
                        stat:bool=False, 
                        limit: int=None,
                        offset: int=0,
                        mlt_count:int=None, 
                        sort:str=None,
                        download:bool=None, 
                        session_info=None
                        ):
    """
    Return the list of documents that cited this journal article.

    period must be either '5', 10, '20', or 'all'

    args:
      limit: the number of records you want to return

    >>> result, status = database_who_cited()
    >>> len(result.documentList.responseSet)>=10
    True

    """
    cited_in_period = opasConfig.normalize_val(cited_in_period, opasConfig.VALS_YEAROPTIONS, default='5')

    if sort is None:
        sort = f"art_cited_{cited_in_period} desc"

    start_year = dtime.date.today().year
    if publication_period is None:
        start_year = None
    else:
        start_year -= publication_period
        start_year = f">{start_year}"

    try:
        solr_query_spec = \
            opasQueryHelper.parse_search_query_parameters(cited_art_id=cited_art_id, 
                                                          source_name=source_name,
                                                          source_code=source_code,
                                                          source_type=source_type, 
                                                          author=author,
                                                          title=title,
                                                          startyear=start_year,
                                                          highlightlimit=0, 
                                                          abstract_requested=abstract_requested,
                                                          similar_count=mlt_count, 
                                                          sort = sort,
                                                          req_url = req_url
                                                        )

        ret_val, ret_status = opasPySolrLib.search_text_qs(solr_query_spec, 
                                             limit=limit,
                                             offset=offset,
                                             #mlt_count=mlt_count, 
                                             session_info=session_info, 
                                             req_url = req_url
                                            )
    except Exception as e:
        logger.warning(f"Who Cited Search error {e}")
        
    return ret_val, ret_status   

#-----------------------------------------------------------------------------
#def database_get_whats_new(days_back=7,
                           #limit=opasConfig.DEFAULT_LIMIT_FOR_WHATS_NEW,
                           #req_url:str=None,
                           #source_type="journal",
                           #offset=0,
                           #session_info=None):
    #"""
    #Return what JOURNALS have been updated in the last week

    #>>> result = database_get_whats_new()

    #"""    
    #field_list = "art_id, title, art_vol, art_iss, art_sourcecode, art_sourcetitlefull, art_sourcetitleabbr, file_last_modified, timestamp, art_sourcetype"
    #sort_by = "file_last_modified"

    ## two ways to get date, slightly different meaning: timestamp:[NOW-{days_back}DAYS TO NOW] AND file_last_modified:[NOW-{days_back}DAYS TO NOW]
    #try:
        #q_str = f"file_last_modified:[NOW-{days_back}DAYS TO NOW] AND art_sourcetype:{source_type}"
        #logger.info(f"Solr Query: q={q_str}")
        #results = solr_docs.query( q = q_str,  
                                   #fl = field_list,
                                   #fq = "{!collapse field=art_sourcecode max=art_year_int}",
                                   #sort=sort_by, sort_order="desc",
                                   #rows=limit, start=offset
                                   #)

        ## logger.debug("databaseWhatsNew Number found: %s", results._numFound)
    #except Exception as e:
        #logger.error(f"Solr Search Exception: {e}")

    #response_info = models.ResponseInfo( count = len(results.results),
                                         #fullCount = results._numFound,
                                         #limit = limit,
                                         #offset = offset,
                                         #listType="newlist",
                                         #fullCountComplete = limit >= results._numFound,
                                         #request=f"{req_url}",
                                         #timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                         #)


    #whats_new_list_items = []
    #row_count = 0
    #already_seen = []
    #for result in results:
        #PEPCode = result.get("art_sourcecode", None)
        ##if PEPCode is None or PEPCode in ["SE", "GW", "ZBK", "IPL"]:  # no books
            ##continue
        #src_type = result.get("art_sourcetype", None)
        #if src_type != "journal":
            #continue

        #volume = result.get("art_vol", None)
        #issue = result.get("art_iss", "")
        #year = result.get("art_year", None)
        #abbrev = result.get("art_sourcetitleabbr", None)
        #src_title = result.get("art_sourcetitlefull", None)
        
        #updated = result.get("file_last_modified", None)
        #updated = updated.strftime('%Y-%m-%d')
        #if abbrev is None:
            #abbrev = src_title
        #display_title = abbrev + " v%s.%s (%s) " % (volume, issue, year)
        #if display_title in already_seen:
            #continue
        #else:
            #already_seen.append(display_title)
        #volume_url = "/v1/Metadata/Contents/%s/%s" % (PEPCode, issue)
        

        #item = models.WhatsNewListItem( documentID = result.get("art_id", None),
                                        #displayTitle = display_title,
                                        #abbrev = abbrev,
                                        #volume = volume,
                                        #issue = issue,
                                        #year = year,
                                        #PEPCode = PEPCode, 
                                        #srcTitle = src_title,
                                        #volumeURL = volume_url,
                                        #updated = updated
                                        #) 
        #whats_new_list_items.append(item)
        #row_count += 1
        #if row_count > limit:
            #break

    #response_info.count = len(whats_new_list_items)

    #whats_new_list_struct = models.WhatsNewListStruct( responseInfo = response_info, 
                                                       #responseSet = whats_new_list_items
                                                       #)

    #ret_val = models.WhatsNewList(whatsNew = whats_new_list_struct)

    #return ret_val   # WhatsNewList

#def metadata_get_volumes(source_code=None,
                         #source_type=None,
                         #req_url: str=None 
                         ##limit=1,
                         ##offset=0
                        #):
    #"""
    #Return a list of volumes
      #- for a specific source_code (code),
      #- OR for a specific source_type (e.g. journal)
      #- OR if source_code and source_type are not specified, bring back them all
      
    #This is a new version (08/2020) using Solr pivoting rather than the OCD database.
      
    #"""
    ## returns multiple gw's and se's, 139 unique volumes counting those (at least in 2020)
    ## works for journal, videostreams have more than one year per vol.
    ## works for books, videostream vol numbers
    ##results = solr_docs.query( q = f"art_sourcecode:{pep_code} && art_year:{year}",  
                                ##fields = "art_sourcecode, art_vol, art_year",
                                ##sort="art_sourcecode, art_year", sort_order="asc",
                                ##fq="{!collapse field=art_vol}",
                                ##rows=limit, start=offset
                                ##)
    
    #distinct_return = "art_sourcecode, art_vol, art_year, art_sourcetype"
    #limit = 6
    #count = 0
    #ret_val = None
    ## normalize source type
    #if source_type is not None: # none is ok
        #source_type = opasConfig.normalize_val(source_type, opasConfig.VALS_SOURCE_TYPE, None)
    
    #q_str = "bk_subdoc:false"
    #if source_code is not None:
        #q_str += f" && art_sourcecode:{source_code}"
    #if source_type is not None:
        #q_str += f" && art_sourcetype:{source_type}"
    #facet_fields = ["art_vol", "art_sourcecode"]
    #facet_pivot = "art_sourcecode,art_year,art_vol" # important ...no spaces!
    #try:
        #logger.info(f"Solr Query: q={q_str} facet='on'")
        #result = solr_docs.query( q = q_str,
                                  #fq="*:*", 
                                  #fields = distinct_return,
                                  #sort="art_sourcecode, art_year", sort_order="asc",
                                  ##fq="{!collapse field=art_sourcecode, art_vol}",
                                  #facet="on", 
                                  #facet_fields = facet_fields, 
                                  #facet_pivot = facet_pivot,
                                  ##facet_offset = offset, 
                                  #facet_mincount=1,
                                  #facet_sort="art_year asc", 
                                  #rows=limit, 
                                  ##start=offset
                                 #)
        #facet_pivot = result.facet_counts["facet_pivot"][facet_pivot]
        ##ret_val = [(piv['value'], [n["value"] for n in piv["pivot"]]) for piv in facet_pivot]

        #response_info = models.ResponseInfo( count = count,
                                             #fullCount = count,
                                             ##limit = limit,
                                             ##offset = offset,
                                             #listType="volumelist",
                                             #fullCountComplete = (limit == 0 or limit >= count),
                                             #request=f"{req_url}",
                                             #timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                             #)

        
        #volume_item_list = []
        #volume_dup_check = {}
        #for m1 in facet_pivot:
            #journal_code = m1["value"] # pepcode
            #seclevel = m1["pivot"]
            #for m2 in seclevel:
                #secfield = m2["field"] # year
                #secval = m2["value"]
                #thirdlevel = m2["pivot"]
                #for m3 in thirdlevel:
                    #thirdfield = m3["field"] # vol
                    #thirdval = m3["value"]
                    #PEPCode = journal_code
                    #year = secval
                    #vol = thirdval
                    #count = m3["count"]
                    #pep_code_vol = PEPCode + vol
                    ## if it's a journal, Supplements are not a separate vol, they are an issue.
                    #if pep_code_vol[-1] == "S" and journal_code not in opasConfig.BOOK_CODES_ALL:
                        #pep_code_vol = pep_code_vol[:-1]
                    #cur_code = volume_dup_check.get(pep_code_vol)
                    #if cur_code is None:
                        #volume_dup_check[pep_code_vol] = [year]
                        #volume_list_item = models.VolumeListItem(PEPCode=PEPCode,
                                                                 #vol=vol,
                                                                 #year=year,
                                                                 #years=[year],
                                                                 #count=count
                        #)
                        #volume_item_list.append(volume_list_item)
                    #else:
                        #volume_dup_check[pep_code_vol].append(year)
                        #if year not in volume_list_item.years:
                            #volume_list_item.years.append(year)
                        #volume_list_item.count += count

                
    #except Exception as e:
        #logger.error(f"Error: {e}")
    #else:
        #response_info.count = len(volume_item_list)
        #response_info.fullCount = len(volume_item_list)
    
        #volume_list_struct = models.VolumeListStruct( responseInfo = response_info, 
                                                      #responseSet = volume_item_list
                                                      #)
    
        #volume_list = models.VolumeList(volumeList = volume_list_struct)
    
        #ret_val = volume_list
        
    #return ret_val

#def metadata_get_next_and_prev_articles(art_id=None, 
                                        #req_url: str=None 
                                       #):
    #"""
    #Return the previous, matching and next article, assuming they all exist.
    #The intent is to be able to have next and previous arrows on the articles.
    
    #>>> prev, match, next = metadata_get_next_and_prev_articles(art_id="APA.066.0159A")
    #>>> prev.get("art_id", None), match.get("art_id", None), next.get("art_id", None)
    #('APA.066.0149A', 'APA.066.0159A', 'APA.066.0167A')
    
    #>>> prev, match, next = metadata_get_next_and_prev_articles(art_id="GW.016.0274A")
    #>>> prev.get("art_id", None), match.get("art_id", None), next.get("art_id", None)
    #('GW.016.0273A', 'GW.016.0274A', 'GW.016.0276A')
    
    #>>> metadata_get_next_and_prev_articles(art_id="GW.016")
    #({}, {}, {})
    
    #New: 2020-11-17      
    #"""
    ## returns multiple gw's and se's, 139 unique volumes counting those (at least in 2020)
    ## works for journal, videostreams have more than one year per vol.
    ## works for books, videostream vol numbers
    ##results = solr_docs.query( q = f"art_sourcecode:{pep_code} && art_year:{year}",  
                                ##fields = "art_sourcecode, art_vol, art_year",
                                ##sort="art_sourcecode, art_year", sort_order="asc",
                                ##fq="{!collapse field=art_vol}",
                                ##rows=limit, start=offset
                                ##)
    
    #source_code, source_year, source_vol, source_page, source_page_id = split_article_id(art_id)
    #distinct_return = "art_sourcecode, art_year, art_vol, art_id"
    #next_art = {}
    #prev_art = {}
    #match_art = {}
    
    #q_str = "art_level:1 "
    #if source_code is not None and source_code.isalpha():
        #q_str += f" && art_sourcecode:{source_code}"

    #if source_vol is not None and source_vol.isalnum():
        #q_str += f" && art_vol:{source_vol}"
        
    #if source_year is not None and source_year.isalnum():
        #q_str += f" && art_year:{source_year}"
        
    #try:
        #logger.info(f"Solr Query: q={q_str}")
        #result = solr_docs.query( q = q_str,
                                  #fq="*:*", 
                                  #fields = distinct_return,
                                  #sort="art_id",
                                  #sort_order="asc",
                                  #rows=100
                                 #)
    #except Exception as e:
        #logger.error(f"Error: {e}")
    #else:
        ## find the doc
        #count = 0
        #for n in result.results:
            #if n["art_id"] == art_id:
                ## we found it
                #match_art = result.results[count]
                #try:
                    #prev_art = result.results[count-1]
                #except:
                    #prev_art = {}
                #try:
                    #next_art = result.results[count+1]
                #except:
                    #next_art = {}
            #else:
                #count += 1
                #continue
    
    #return prev_art, match_art, next_art

#def metadata_get_next_and_prev_vols(source_code=None,
                                    #source_vol=None,
                                    #req_url: str=None 
                                   #):
    #"""
    #Return previous, matched, and next volume for the source code and year.
    #New: 2020-11-17

    #>>> metadata_get_next_and_prev_vols(source_code="APA", source_vol="66")
    #({'value': '65', 'count': 89, 'year': '2017'}, {'value': '66', 'count': 95, 'year': '2018'}, {'value': '67', 'count': 88, 'year': 'APA'})
    
    #>>> metadata_get_next_and_prev_vols(source_code="GW", source_vol="16")
    #({'value': '15', 'count': 1, 'year': '1933'}, {'value': '16', 'count': 1, 'year': '1993'}, None)
    
    #>>> metadata_get_next_and_prev_vols(source_code="GW")
    #(None, None, None)
    
    #>>> metadata_get_next_and_prev_vols(source_vol="66")
    #(None, None, None)
    
    #>>> metadata_get_next_and_prev_vols(source_vol=66)
    #(None, None, None)
    
    #>>> metadata_get_next_and_prev_vols(source_code="GW", source_vol=16)
    #({'value': '15', 'count': 1, 'year': '1933'}, {'value': '16', 'count': 1, 'year': '1993'}, None)

    #"""
    ## returns multiple gw's and se's, 139 unique volumes counting those (at least in 2020)
    ## works for journal, videostreams have more than one year per vol.
    ## works for books, videostream vol numbers
    ##results = solr_docs.query( q = f"art_sourcecode:{pep_code} && art_year:{year}",  
                                ##fields = "art_sourcecode, art_vol, art_year",
                                ##sort="art_sourcecode, art_year", sort_order="asc",
                                ##fq="{!collapse field=art_vol}",
                                ##rows=limit, start=offset
                                ##)
    
    #distinct_return = "art_sourcecode, art_year, art_vol"
    #next_vol = None
    #prev_vol = None
    #match_vol = None
    
    #q_str = "bk_subdoc:false"
    #if source_code is None:
        #logger.error("No source code (e.g., journal code) provided;")
    #else:
        #q_str += f" && art_sourcecode:{source_code}"

        #if source_vol is None:
            #logger.error("No vol number provided;")
        #else:
            #source_vol_int = int(source_vol)
            #next_source_vol_int = source_vol_int + 1
            #prev_source_vol_int = source_vol_int - 1
            #q_str += f" && art_vol:({source_vol} || {next_source_vol_int} || {prev_source_vol_int})"
        
            #facet_fields = ["art_vol", "art_sourcecode"]
            #facet_pivot_fields = "art_sourcecode,art_year,art_vol" # important ...no spaces!
            #try:
                #logger.info(f"Solr Query: q={q_str}")
                #result = solr_docs.query( q = q_str,
                                          #fq="*:*", 
                                          #fields = distinct_return,
                                          #sort="art_sourcecode, art_year", sort_order="asc",
                                          ##fq="{!collapse field=art_sourcecode, art_vol}",
                                          #facet="on", 
                                          #facet_fields = facet_fields, 
                                          #facet_pivot = facet_pivot_fields,
                                          #facet_mincount=1,
                                          #facet_sort="art_year asc", 
                                          ##rows=limit, 
                                          ##start=offset
                                         #)
                #facet_pivot = result.facet_counts["facet_pivot"][facet_pivot_fields]
                ##ret_val = [(piv['value'], [n["value"] for n in piv["pivot"]]) for piv in facet_pivot]
            #except Exception as e:
                #logger.error(f"Error: {e}")
            #else:
                #prev_vol = None
                #match_vol = None
                #next_vol = None
                #if facet_pivot != []:
                    #next_vol_idx = None
                    #prev_vol_idx = None
                    #match_vol_idx = None
                    #pivot_len = len(facet_pivot[0]['pivot'])
                    #counter = 0
                    #for n in facet_pivot[0]['pivot']:
                        #if n['pivot'][0]['value'] == str(source_vol):
                            #match_vol_idx = counter
                            #match_vol = n['pivot'][0]
                            #match_vol_year = n['value']
                            #match_vol['year'] = match_vol_year
                            #del(match_vol['field'])
                        #counter += 1
        
                    #if match_vol_idx is not None:
                        #if match_vol_idx > 0:
                            #prev_vol_idx = match_vol_idx - 1
                            #prev_vol = facet_pivot[0]['pivot'][prev_vol_idx]
                            #prev_vol_year = prev_vol['value']
                            #prev_vol = prev_vol['pivot'][0]
                            #prev_vol['year'] = prev_vol_year
                            #del(prev_vol['field'])
                            
                        #if match_vol_idx < pivot_len - 1:
                            #next_vol_idx = match_vol_idx + 1
                            #next_vol = facet_pivot[0]['pivot'][next_vol_idx]
                            #next_vol_year = facet_pivot[0]['value']
                            #next_vol = next_vol['pivot'][0]
                            #next_vol['year'] = next_vol_year
                            #del(next_vol['field'])
                    #else:
                        #logger.warning("No volume to assess: ", match_vol_idx)
    
    #return prev_vol, match_vol, next_vol

#-----------------------------------------------------------------------------
#def metadata_get_contents(pep_code, #  e.g., IJP, PAQ, CPS
                          #year="*",
                          #vol="*",
                          #req_url: str=None,
                          #extra_info:int=0, # since this requires an extra query of the DB
                          #limit=opasConfig.DEFAULT_LIMIT_FOR_CONTENTS_LISTS,
                          #offset=0):
    #"""
    #Return a source's contents

    #>>> results = metadata_get_contents("IJP", "1993", limit=5, offset=0)
    #>>> results.documentList.responseInfo.count == 5
    #True
    #>>> results = metadata_get_contents("IJP", "1993", limit=5, offset=5)
    #>>> results.documentList.responseInfo.count == 5
    #True
    #"""
    #ret_val = []
    #if year == "*" and vol != "*":
        ## specified only volume
        #field="art_vol"
        #search_val = vol
    #else:  #Just do year
        #field="art_year"
        #search_val = year  #  was "*", thats an error, fixed 2019-12-19

    #try:
        #code = pep_code.upper()
    #except:
        #logger.warning(f"Illegal PEP Code or None supplied to metadata_get_contents: {pep_code}")
    #else:
        #pep_code = code

    #q_str = f"art_sourcecode:{pep_code} && {field}:{search_val}"
    #logger.info(f"Solr Query: q:{q_str}")
    #results = solr_docs.query(q = q_str,  
                              #fields = """art_id,
                                          #art_vol,
                                          #art_year,
                                          #art_iss,
                                          #art_iss_title,
                                          #art_iss_seqnbr,
                                          #art_newsecnm,
                                          #art_pgrg,
                                          #title,
                                          #art_authors,
                                          #art_authors_mast,
                                          #art_citeas_xml,
                                          #art_info_xml""",
                              #sort="art_id", sort_order="asc",
                              #rows=limit, start=offset
                             #)
    
    #document_item_list = []
    #for result in results.results:
        ## transform authorID list to authorMast
        #author_ids = result.get("art_authors", None)
        #if author_ids is None:
            ## try this, instead of abberrant behavior in alpha of display None!
            #authorMast = result.get("art_authors_mast", "")
        #else:
            #authorMast = opasgenlib.derive_author_mast(author_ids)

        #pgRg = result.get("art_pgrg", None)
        #pgStart, pgEnd = opasgenlib.pgrg_splitter(pgRg)
        #citeAs = result.get("art_citeas_xml", None)  
        #citeAs = opasQueryHelper.force_string_return_from_various_return_types(citeAs)
        #vol = result.get("art_vol", None)
        #issue = result.get("art_iss", None)
        #issue_title = result.get("art_iss_title", None)
        #issue_seqnbr = result.get("art_iss_seqnbr", None)
        #if issue is not None:
            #if issue_title is None:
                #if issue_seqnbr is None:
                    #issue_title = f"Issue {issue}"
                #else:
                    #issue_title = f"No. {issue_seqnbr}"
        #item = models.DocumentListItem(PEPCode = pep_code, 
                                       #year = result.get("art_year", None),
                                       #vol = vol,
                                       #issue = issue,
                                       #issueTitle = issue_title,
                                       #issueSeqNbr = issue_seqnbr, 
                                       #newSectionName = result.get("art_newsecnm", None),
                                       #pgRg = result.get("art_pgrg", None),
                                       #pgStart = pgStart,
                                       #pgEnd = pgEnd,
                                       #title = result.get("title", None), 
                                       #authorMast = authorMast,
                                       #documentID = result.get("art_id", None),
                                       #documentRef = opasxmllib.xml_elem_or_str_to_text(citeAs, default_return=""),
                                       #documentRefHTML = citeAs,
                                       #documentInfoXML=result.get("art_info_xml", None), 
                                       #score = result.get("score", None)
                                       #)
        ##logger.debug(item)
        #document_item_list.append(item)

    ## two options 2020-11-17 for extra info (lets see timing for each...)
    #suppinfo = None
    #if extra_info == 1 and search_val != "*" and pep_code != "*" and len(results.results) > 0:
        #ocd = opasCentralDBLib.opasCentralDB()
        #suppinfo = ocd.get_min_max_volumes(source_code=pep_code)

    #if extra_info == 2 and search_val != "*" and pep_code != "*" and len(results.results) > 0:
        #prev_vol, match_vol, next_vol = opasPySolrLib.metadata_get_next_and_prev_vols(source_code=pep_code,
                                                                        #source_vol=vol,
                                                                        #req_url=req_url
                                                                        #)
        #suppinfo = {"infosource": "volumes_adjacent",
                    #"prev_vol": prev_vol,
                    #"matched_vol": match_vol,
                    #"next_vol": next_vol}

    #response_info = models.ResponseInfo( count = len(results.results),
                                         #fullCount = results._numFound,
                                         #limit = limit,
                                         #offset = offset,
                                         #listType="documentlist",
                                         #fullCountComplete = limit >= results._numFound,
                                         #supplementalInfo=suppinfo, 
                                         #request=f"{req_url}",
                                         #timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                         #)

    #document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                      #responseSet=document_item_list
                                                      #)

    #document_list = models.DocumentList(documentList = document_list_struct)

    #ret_val = document_list

    #return ret_val

#-----------------------------------------------------------------------------
def metadata_get_database_statistics(session_info=None):
    """
    Return counts for the annual summary (or load checks)

    >>> results = metadata_get_database_statistics()
    >>> results.article_count > 135000
    True
    """
    content = models.ServerStatusContent()
    
    # data = metadata_get_volumes(source_code="IJPSP")
    documentList, ret_status = search_text(query=f"art_id:*", 
                                               limit=1,
                                               facet_fields="art_year,art_pgcount,art_figcount,art_sourcetitleabbr", 
                                               abstract_requested=False,
                                               full_text_requested=False,
                                               session_info=session_info
                                               )
    
    bookList, ret_status = search_text(query=f"art_sourcecode:(ZBK || IPL || NLP)", 
                                               limit=1,
                                               facet_fields="art_product_key", 
                                               abstract_requested=False,
                                               full_text_requested=False, 
                                               session_info=session_info
                                               )
    
    videoList, ret_status = search_text(query=f"art_sourcecode:*VS", 
                                               limit=1,
                                               facet_fields=None, 
                                               abstract_requested=False,
                                               full_text_requested=False, 
                                               session_info=session_info
                                               )

    content.article_count = documentList.documentList.responseInfo.fullCount
    facet_counts = documentList.documentList.responseInfo.facetCounts
    facet_fields = facet_counts["facet_fields"]
    src_counts = facet_fields["art_sourcetitleabbr"]
    fig_counts = facet_fields["art_figcount"]
    content.figure_count = sum([int(y) for x,y in fig_counts.items() if x != '0'])
    journals_plus_videos = [x for x,y in src_counts.items() if x not in ("ZBK", "IPL", "NLP", "SE", "GW")]
    journals = [x for x in journals_plus_videos if re.match(".*VS", x) is None]
    content.journal_count = len(journals)
    content.video_count = videoList.documentList.responseInfo.fullCount
    book_facet_counts = bookList.documentList.responseInfo.facetCounts
    book_facet_fields = book_facet_counts["facet_fields"]
    book_facet_product_keys = book_facet_fields["art_product_key"]
    content.book_count = len(book_facet_product_keys)
    content.source_count = dict(OrderedDict(sorted(src_counts.items(), key=lambda t: t[0])))
    vols = opasPySolrLib.metadata_get_volumes(source_type="journal")    
    content.vol_count = vols.volumeList.responseInfo.fullCount
    year_counts = facet_fields["art_year"]
    years = [int(x) for x,y in year_counts.items()]
    content.year_first = min(years)
    content.year_last = max(years)
    content.year_count = content.year_last - content.year_first
    page_counts = facet_fields["art_pgcount"]
    pages = [int(x) *int(y) for x,y in page_counts.items()]
    content.page_count = sum(pages)
    content.page_height_feet = int(((content.page_count * .1) / 25.4) / 12) # page thickness in mm, 25.4 mm per inch, 12 inches per foot
    content.page_weight_tons = int(content.page_count * 4.5 * 0.000001)
    source_count_html = "<ul>"
    for code, cnt in content.source_count.items():
        source_count_html += f"<li>{code} - {cnt}</li>"
    source_count_html += "</ul>"
   
    content.description_html = f"""
<p>This release of PEP-Web contains the complete text and illustrations of
{content.journal_count} premier journals in psychoanalysis,
{content.book_count} classic psychoanalytic books, and the full text and Editorial notes of the
24 volumes of the Standard Edition of the Complete Psychological Works of Sigmund Freud as well as the
19 volume German Freud Standard Edition Gesammelte Werke.  It spans over
{content.year_count} publication years and contains the full text of articles whose source ranges from
{content.year_first} through {content.year_last}.</p>
<p>
There are over
{content.article_count} articles and almost
{content.figure_count} figures and illustrations that originally resided on
{content.vol_count} volumes with over
{content.page_count/100000:.2f} million printed pages. In hard copy, the PEP Archive represents a stack of paper more than
{content.page_height_feet} feet high and weighing over
{content.page_weight_tons} tons!
</p>
"""
    
    content.source_count_html = f"""
<p>
\nCount of Articles by Source:
\n{source_count_html}
</p>
"""
        
    ret_val = content
    return ret_val

#-----------------------------------------------------------------------------
#def metadata_get_videos(src_type=None, pep_code=None, limit=opasConfig.DEFAULT_LIMIT_FOR_METADATA_LISTS, offset=0):
    #"""
    #Fill out a sourceInfoDBList which can be used for a getSources return, but return individual 
      #videos, as is done for books.  This provides more information than the 
      #original API which returned video "journals" names.
      
    #Authorizations are not checked or returned (thus no session id is needed)

    #"""
    #source_info_dblist = []
    #total_count = 0
    #ret_val = {}
    #return_status = (200, "OK")

    #if pep_code is not None:
        #q_str = "art_sourcetype:video* AND art_sourcecode:{}".format(pep_code)
    #else:
        #q_str = "art_sourcetype:video*"
        
    #try:
        #logger.info(f"Solr Query: q={q_str}")
        #srcList = solr_docs.query(q = q_str,  
                                  #fields = opasConfig.DOCUMENT_ITEM_VIDEO_FIELDS,
                                  #sort = "art_citeas_xml",
                                  #sort_order = "asc",
                                  #rows=limit, start=offset
                                  #)
    #except solr.SolrException as e:
        #if e is None:
            #ret_val = models.ErrorReturn(httpcode=httpCodes.HTTP_400_BAD_REQUEST, error="Solr engine returned an unknown error", error_description=f"Solr engine returned error without a reason")
            #ret_status = (e.httpcode, None) # e has type <class 'solrpy.core.SolrException'>,with useful elements of httpcode, reason, and body
            #logger.error(f"Solr Runtime Search Error (a): {e.reason}")
            #logger.error(e.body)
        #elif e.reason is not None:
            #ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Solr engine returned an unknown error", error_description=f"Solr engine returned error {e.httpcode} - {e.reason}")
            #ret_status = (e.httpcode, e) # e has type <class 'solrpy.core.SolrException'>,with useful elements of httpcode, reason, and body
            #logger.error(f"Solr Runtime Search Error (b): {e.reason}")
            #logger.error(e.body)
        #else:
            #ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Search syntax error", error_description=f"There's an error in your input (no reason supplied)")
            #ret_status = (e.httpcode, e) # e has type <class 'solrpy.core.SolrException'>,with useful elements of httpcode, reason, and body
            #logger.error(f"Solr Runtime Search Error (c): {e.httpcode}")
            #logger.error(e.body)
        
    #except SAXParseException as e:
        #ret_val = models.ErrorReturn(httpcode=httpCodes.HTTP_400_BAD_REQUEST, error="Search syntax error", error_description=f"{e.getMessage()}")
        #ret_status = (httpCodes.HTTP_400_BAD_REQUEST, e) # e has type <class 'solrpy.core.SolrException'>, with useful elements of httpcode, reason, and body, e.g.,
        #logger.error(f"Solr Runtime Search Error (parse): {ret_val}. Params sent: {solr_param_dict}")
                                
    #except Exception as e:
        #logger.error("metadataGetVideos Error: {}".format(e))
        #ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Search syntax error", error_description=f"There's an error in your input (no reason supplied)")
        #ret_status = (httpCodes.HTTP_400_BAD_REQUEST, e) # e has type <class 'solrpy.core.SolrException'>, with useful elements of httpcode, reason, and body, e.g.,
        #logger.error(f"Solr Runtime Search Error (syntax): {e.httpcode}. Params sent: {solr_param_dict}")
        #logger.error(e.body)
    #else:
        ## count = len(srcList.results)
        #total_count = int(srcList.results.numFound)
    
        #for result in srcList.results:
            #source_info_record = {}
            #authors = result.get("art_authors")
            #if authors is None:
                #source_info_record["author"] = None
            #elif len(authors) > 1:
                #source_info_record["author"] = "; ".join(authors)
            #else:    
                #source_info_record["author"] = authors[0]
    
            #source_info_record["src_code"] = result.get("art_sourcecode")
            #source_info_record["ISSN"] = result.get("art_issn")
            #source_info_record["documentID"] = result.get("art_id")
            #try:
                #source_info_record["title"] = result.get("title")
            #except:
                #source_info_record["title"] = ""
    
            #source_info_record["art_citeas"] = result.get("art_citeas_xml")
            #source_info_record["pub_year"] = result.get("art_year")
            #source_info_record["bib_abbrev"] = result.get("art_sourcetitleabbr")  # error in get field, fixed 2019.12.19
            #try:
                #source_info_record["language"] = result.get("art_lang")
            #except:
                #source_info_record["language"] = "EN"
    
            #logger.debug("metadataGetVideos: %s", source_info_record)
            #source_info_dblist.append(source_info_record)

    #return total_count, source_info_dblist, ret_val, return_status

#-----------------------------------------------------------------------------
def metadata_get_source_info(src_type=None, # opasConfig.VALS_PRODUCT_TYPES
                             src_code=None,
                             src_name=None, 
                             req_url: str=None, 
                             limit=opasConfig.DEFAULT_LIMIT_FOR_METADATA_LISTS,
                             offset=0):
    """
    Return a list of source metadata, by type (e.g., journal, book, video, stream.)

    NOTE: Stream is equiv to journal for videos. Video is more like books, individual videos).

    No attempt here to map to the correct structure, just checking what field/data items we have in sourceInfoDB.

    >>> results = metadata_get_source_info(src_code="APA")
    >>> results.sourceInfo.responseInfo.count == 1
    True
    >>> results = metadata_get_source_info(src_type="journal", limit=3)
    >>> results.sourceInfo.responseInfo.count >= 3
    True
    >>> results = metadata_get_source_info(src_type="book", limit=10)
    >>> results.sourceInfo.responseInfo.count >= 10
    True
    >>> results = metadata_get_source_info(src_type="journals", limit=10, offset=0)
    >>> results.sourceInfo.responseInfo.count >= 10
    True
    >>> results = metadata_get_source_info(src_type="journals", limit=10, offset=6)
    >>> results.sourceInfo.responseInfo.count >= 10
    True

    >>> results = metadata_get_source_info()
    >>> results.sourceInfo.responseInfo.fullCount
    191
    
    """
    ret_val = []
    source_info_dblist = []
    err = None
    ocd = opasCentralDBLib.opasCentralDB()
    # standardize Source type, allow plural, different cases, but code below this part accepts only those three.
    if src_type is not None and src_type != "*":
        src_type_in = src_type # save it for logging
        src_type = opasConfig.normalize_val(src_type, opasConfig.VALS_PRODUCT_TYPES)
        if src_type == None:
            err = f"Bad source type: {src_type_in}"
            logger.error(err)
            raise Exception(err)

    if src_type == "videos":
        total_count, source_info_dblist, ret_val, return_status = opasPySolrLib.metadata_get_videos(src_type=src_type, pep_code=src_code, limit=limit, offset=offset)
        count = len(source_info_dblist)
        if return_status != (200, "OK"):
            raise Exception(return_status(1))
    else: # get from mySQL
        try:
            # print(src_type, src_code, src_name, limit, offset)
            total_count, source_info_dblist = ocd.get_sources(src_type = src_type, src_code=src_code, src_name=src_name, limit=limit, offset=offset)
            if source_info_dblist is not None:
                count = len(source_info_dblist)
            else:
                count = 0
            logger.debug("MetadataGetSourceByType: Number found: %s", count)
        except Exception as e:
            errMsg = "MetadataGetSourceByType: Error getting source information.  {}".format(e)
            count = 0
            logger.warning(errMsg)

    response_info = models.ResponseInfo( count = count,
                                         fullCount = total_count,
                                         fullCountComplete = count == total_count,
                                         limit = limit,
                                         offset = offset,
                                         listLabel = "{} List".format(src_type),
                                         listType = "sourceinfolist",
                                         scopeQuery = [src_type, src_code],
                                         request=f"{req_url}",
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                         )

    source_info_listitems = []
    counter = 0
    if count > 0:
        for source in source_info_dblist:
            counter += 1
            err = 0
            if counter < offset:
                continue
            if counter > limit:
                break
            try:
                title = source.get("title")
                authors = source.get("author")
                pub_year = source.get("pub_year")
                publisher = source.get("bib_abbrev")
                book_code = None
                # src_type = source.get("product_type")
                start_year = source.get("yearFirst")
                end_year = source.get("yearLast")
                base_code = source.get("basecode")
                instance_count = source.get("instances", 1)
                documentID = source.get("documentID", source.get("articleID"))
                if start_year is None:
                    start_year = pub_year
                if end_year is None:
                    end_year = pub_year
    
                if src_type == "book":
                    book_code = source.get("pepcode")
                    if book_code is None:
                        logger.warning(f"Book code information missing for requested basecode {base_code} in productbase")
                    else:
                        m = re.match("(?P<code>[a-z]+)(?P<num>[0-9]+)", book_code, re.IGNORECASE)
                        if m is not None:
                            code = m.group("code")
                            num = m.group("num")
                            book_code = code + "." + num
    
                        art_citeas = u"""<p class="citeas"><span class="authors">%s</span> (<span class="year">%s</span>) <span class="title">%s</span>. <span class="publisher">%s</span>.""" \
                            %                   (authors,
                                                 pub_year,
                                                 title,
                                                 publisher
                                                 )
                elif src_type == "videos":
                    art_citeas = source.get("art_citeas")
                else:
                    art_citeas = title # journals just should show display title
    
                try:
                    item = models.SourceInfoListItem( sourceType = src_type,
                                                      PEPCode = base_code,
                                                      authors = authors,
                                                      pub_year = pub_year,
                                                      documentID = documentID,
                                                      displayTitle = art_citeas,
                                                      title = title,
                                                      srcTitle = title,  # v1 Deprecated for future
                                                      bookCode = book_code,
                                                      abbrev = source.get("bibabbrev"),
                                                      bannerURL = f"{localsecrets.APIURL}/{opasConfig.IMAGES}/banner{source.get('basecode')}Logo.gif",
                                                      language = source.get("language"),
                                                      ISSN = source.get("ISSN"),
                                                      ISBN10 = source.get("ISBN-10"),
                                                      ISBN13 = source.get("ISBN-13"),
                                                      yearFirst = start_year,
                                                      yearLast = end_year,
                                                      instanceCount = instance_count, 
                                                      embargoYears = source.get("embargo")
                                                      ) 
                except ValidationError as e:
                    logger.error("metadataGetSourceByType SourceInfoListItem Validation Error:")
                    logger.error(e.json())
                    err = 1
    
            except Exception as e:
                logger.error("metadataGetSourceByType: Exception: %s", e)
                err = 1
    
            if err == 0:
                source_info_listitems.append(item)
    



    try:
        source_info_struct = models.SourceInfoStruct( responseInfo = response_info, 
                                                      responseSet = source_info_listitems
                                                      )
    except ValidationError as e:
        logger.error("models.SourceInfoStruct Validation Error:")
        logger.error(e.json())        

    try:
        source_info_list = models.SourceInfoList(sourceInfo = source_info_struct)
    except ValidationError as e:
        logger.error("SourceInfoList Validation Error:")
        logger.error(e.json())        

    ret_val = source_info_list

    return ret_val

##-----------------------------------------------------------------------------
#def authors_get_author_info(author_partial,
                            #req_url:str=None, 
                            #limit=opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, offset=0, author_order="index"):
    #"""
    #Returns a list of matching names (per authors last name), and the number of articles in PEP found by that author.

    #Args:
        #author_partial (str): String prefix of author names to return.
        #limit (int, optional): Paging mechanism, return is limited to this number of items.
        #offset (int, optional): Paging mechanism, start with this item in limited return set, 0 is first item.
        #author_order (str, optional): Return the list in this order, per Solr documentation.  Defaults to "index", which is the Solr determined indexing order.

    #Returns:
        #models.DocumentList: Pydantic structure (dict) for DocumentList.  See models.py

    #Docstring Tests:    
        #>>> resp = authors_get_author_info("Tuck")
        #>>> resp.authorIndex.responseInfo.count >= 7
        #True
        #>>> resp = authors_get_author_info("Levins.*", limit=5)
        #>>> resp.authorIndex.responseInfo.count
        #5
    #"""
    #ret_val = {}
    #method = 2

    #if method == 1:
        #query = "art_author_id:/%s.*/" % (author_partial)
        #results = solr_authors.query( q=query,
                                      #fields="authors, art_author_id",
                                      #facet_field="art_author_id",
                                      #facet="on",
                                      #facet_sort=author_order,  # index or count (updated 20200418)
                                      #facet_prefix="%s" % author_partial,
                                      #facet_limit=limit,
                                      #facet_offset=offset,
                                      #rows=0
                                      #)       

    #if method == 2:
        ## should be faster way, but about the same measuring tuck (method1) vs tuck.* (method2) both about 2 query time.  However, allowing regex here.
        #if "*" in author_partial or "?" in author_partial or "." in author_partial:
            #results = solr_authors_term_search( terms_fl="art_author_id",
                                                #terms_limit=limit,  # this causes many regex expressions to fail
                                               #terms_regex=author_partial.lower() + ".*",
                                               #terms_sort=author_order  # index or count
                                               #)           
        #else:
            #results = solr_authors_term_search( terms_fl="art_author_id",
                                                #terms_prefix=author_partial.lower(),
                                               #terms_sort=author_order,  # index or count
                                               #terms_limit=limit
                                               #)

    #response_info = models.ResponseInfo( limit=limit,
                                         #offset=offset,
                                         #listType="authorindex",
                                         #scopeQuery=[f"Terms: {author_partial}"],
                                         #solrParams=results._params,
                                         #request=f"{req_url}",
                                         #timeStamp=datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)
                                         #)

    #author_index_items = []
    #if method == 1:
        #for key, value in results.facet_counts["facet_fields"]["art_author_id"].items():
            #if value > 0:
                #item = models.AuthorIndexItem(authorID = key, 
                                              #publicationsURL = "/v1/Authors/Publications/{}/".format(key),
                                              #publicationsCount = value,
                                              #) 
                #author_index_items.append(item)
                #logger.debug ("authorsGetAuthorInfo", item)

    #if method == 2:  # faster way
        #for key, value in results.terms["art_author_id"].items():
            #if value > 0:
                #item = models.AuthorIndexItem(authorID = key, 
                                              #publicationsURL = "/v1/Authors/Publications/{}/".format(key),
                                              #publicationsCount = value,
                                              #) 
                #author_index_items.append(item)
                #logger.debug("authorsGetAuthorInfo: %s", item)

    #response_info.count = len(author_index_items)
    #response_info.fullCountComplete = limit >= response_info.count

    #author_index_struct = models.AuthorIndexStruct( responseInfo = response_info, 
                                                    #responseSet = author_index_items
                                                    #)

    #author_index = models.AuthorIndex(authorIndex = author_index_struct)

    #ret_val = author_index
    #return ret_val

##-----------------------------------------------------------------------------
#def authors_get_author_publications(author_partial,
                                    #req_url:str=None, 
                                    #limit=opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS,
                                    #offset=0):
    #"""
    #Returns a list of publications (per authors partial name), and the number of articles by that author.

    #>>> ret_val =authors_get_author_publications(author_partial="Tuck") # doctest: +ELLIPSIS
    #>>> type(ret_val)
    #<class 'models.AuthorPubList'>
    #>>> print (f"{ret_val}"[0:68])
    #authorPubList=AuthorPubListStruct(responseInfo=ResponseInfo(count=15
    #>>> ret_val=authors_get_author_publications(author_partial="Fonag")
    #>>> print (f"{ret_val}"[0:68])
    #authorPubList=AuthorPubListStruct(responseInfo=ResponseInfo(count=15
    #>>> ret_val=authors_get_author_publications(author_partial="Levinson, Nadine A.")
    #>>> print (f"{ret_val}"[0:67])
    #authorPubList=AuthorPubListStruct(responseInfo=ResponseInfo(count=8
    #"""
    #ret_val = {}
    #query = "art_author_id:/{}/".format(author_partial)
    #aut_fields = "art_author_id, art_year_int, art_id, art_auth_pos_int, art_author_role, art_author_bio, art_citeas_xml"
    ## wildcard in case nothing found for #1
    #results = solr_authors.query( q = "{}".format(query),   
                                  #fields = aut_fields,
                                  #sort="art_author_id, art_year_int", sort_order="asc",
                                  #rows=limit, start=offset
                                  #)

    #logger.debug("Author Publications: Number found: %s", results._numFound)

    #if results._numFound == 0:
        #logger.debug("Author Publications: Query didn't work - %s", query)
        #query = "art_author_id:/{}[ ]?.*/".format(author_partial)
        #logger.debug("Author Publications: trying again - %s", query)
        #results = solr_authors.query( q = "{}".format(query),  
                                      #fields = aut_fields,
                                      #sort="art_author_id, art_year_int", sort_order="asc",
                                      #rows=limit, start=offset
                                      #)

        #logger.debug("Author Publications: Number found: %s", results._numFound)
        #if results._numFound == 0:
            #query = "art_author_id:/(.*[ ])?{}[ ]?.*/".format(author_partial)
            #logger.debug("Author Publications: trying again - %s", query)
            #results = solr_authors.query( q = "{}".format(query),  
                                          #fields = aut_fields,
                                          #sort="art_author_id, art_year_int", sort_order="asc",
                                          #rows=limit, start=offset
                                          #)

    #response_info = models.ResponseInfo( count = len(results.results),
                                         #fullCount = results._numFound,
                                         #limit = limit,
                                         #offset = offset,
                                         #listType="authorpublist",
                                         #scopeQuery=[query],
                                         #solrParams = results._params,
                                         #fullCountComplete = limit >= results._numFound,
                                         #request=f"{req_url}",
                                         #timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                         #)

    #author_pub_list_items = []
    #for result in results.results:
        #citeas = result.get("art_citeas_xml", None)
        #citeas = opasQueryHelper.force_string_return_from_various_return_types(citeas)

        #item = models.AuthorPubListItem( authorID = result.get("art_author_id", None), 
                                         #documentID = result.get("art_id", None),
                                         #documentRefHTML = citeas,
                                         #documentRef = opasxmllib.xml_elem_or_str_to_text(citeas, default_return=""),
                                         #documentURL = opasConfig.API_URL_DOCUMENTURL + result.get("art_id", None),
                                         #year = result.get("art_year", None),
                                         #score = result.get("score", 0)
                                         #) 

        #author_pub_list_items.append(item)

    #response_info.count = len(author_pub_list_items)

    #author_pub_list_struct = models.AuthorPubListStruct( responseInfo = response_info, 
                                                         #responseSet = author_pub_list_items
                                           #)

    #author_pub_list = models.AuthorPubList(authorPubList = author_pub_list_struct)

    #ret_val = author_pub_list
    #return ret_val

#-----------------------------------------------------------------------------
def documents_get_abstracts(document_id,
                            ret_format="TEXTONLY",
                            authenticated=False,
                            similar_count=0,
                            sort: str=None, 
                            limit=opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS,
                            req_url: str=None, 
                            offset=0,
                            session_info=None
                            ):
    """
    Returns an abstract or summary for the specified document
    If part of a documentID is supplied, multiple abstracts will be returned.

    The endpoint reminds me that we should be using documentID instead of "art" for article perhaps.
      Not thrilled about the prospect of changing it, but probably the right thing to do.

    >>> results = documents_get_abstracts("IJP.075")
    >>> results.documents.responseInfo.count == 15
    True
    >>> results = documents_get_abstracts("AIM.038.0279A")  # no abstract on this one
    >>> results.documents.responseInfo.count == 1
    True
    >>> results = documents_get_abstracts("AIM.040.0311A")
    >>> results.documents.responseInfo.count == 1
    True

    """
    ret_val = None

    if document_id is not None:
        try:
            document_id = document_id.upper()
        except Exception as e:
            logger.warning("Bad argument {document_id} to get_abstract(Error:{e})")
            return ret_val

        if sort is None:
            sort="art_citeas_xml asc"

        document_list, ret_status = search_text( query="art_id:%s*" % (document_id),
                                                 full_text_requested=False,
                                                 abstract_requested=True, 
                                                 format_requested = ret_format,
                                                 #authenticated=authenticated,
                                                 similar_count=similar_count,
                                                 facet_fields=opasConfig.DOCUMENT_VIEW_FACET_LIST,
                                                 facet_mincount=1,
                                                 sort=sort, 
                                                 limit=limit,   
                                                 offset=offset, 
                                                 req_url=req_url,
                                                 session_info=session_info
                                                 )

        documents = models.Documents(documents = document_list.documentList)

        ret_val = documents

    return ret_val

#-----------------------------------------------------------------------------
def documents_get_document(document_id,
                           solr_query_spec=None,
                           ret_format="XML",
                           similar_count=0,
                           #file_classification=None,
                           req_url:str=None, 
                           page_offset=None,
                           page_limit=None,
                           page=None, 
                           authenticated=True,
                           session_info=None, 
                           option_flags=0
                           ):
    """
    For non-authenticated users, this endpoint returns only Document summary information (summary/abstract)
    For authenticated users, it returns with the document itself

    >> resp = documents_get_document("AIM.038.0279A", ret_format="html") 

    >> resp = documents_get_document("AIM.038.0279A") 

    >> resp = documents_get_document("AIM.040.0311A")


    """
    ret_val = None
    document_list = None
    # search_text_qs handles the authentication verification

    try: # Solr match against art_id is case sensitive
        document_id = document_id.upper()
    except Exception as e:
        logger.warning("Bad argument {document_id} to documents_get_document(Error:{e})")
        return ret_val
    else:
        m = re.match("(?P<docid>(?P<scode>[A-Z]+)\.(?P<svol>[0-9]{3,3})\.(?P<spage>[0-9]{4,4}[A-Z]))(\.P0{0,3}(?P<pagejump>[0-9]{1,4}))?", document_id)
        if m is not None:
            if m.group("pagejump") is not None:
                document_id = m.group("docid")
                # only if they haven't directly specified page
                if page == None:
                    page = m.group("pagejump")
        # just to be sure
        query = "*:*"
        if solr_query_spec is not None:
            solr_query_params = solr_query_spec.solrQuery
            # repeat the query that the user had done when retrieving the document
            query = f"{solr_query_params.searchQ}"
            if query == "":
                query = "*:*"
                search_context = None
            else:
                search_context = query
            filterQ = f"art_id:{document_id} && {solr_query_params.filterQ}"
            # solrParams = solr_query_params.dict() 
        else:
            query = f"art_id:{document_id}"
            filterQ = None
            #solrMax = None
            # solrParams = None

        solr_query_spec = \
                opasQueryHelper.parse_to_query_spec(query = query,
                                                    filter_query = filterQ,
                                                    similar_count=similar_count, 
                                                    full_text_requested=True,
                                                    abstract_requested=True,
                                                    format_requested=ret_format,
                                                    #return_field_set=return_field_set, 
                                                    #summary_fields = summary_fields,  # deprecate?
                                                    highlight_fields = "text_xml, art_title",
                                                    facet_fields=opasConfig.DOCUMENT_VIEW_FACET_LIST,
                                                    facet_mincount=1,
                                                    extra_context_len=opasConfig.SOLR_HIGHLIGHT_RETURN_FRAGMENT_SIZE, 
                                                    limit = 1,
                                                    page_offset = page_offset,
                                                    page_limit = page_limit,
                                                    page = page,
                                                    req_url = req_url, 
                                                    option_flags=option_flags # dictionary of return options
                                                    )

        document_list, ret_status = opasPySolrLib.search_text_qs(solr_query_spec,
                                                                 session_info=session_info
                                                                 )

        try:
            matches = document_list.documentList.responseInfo.count
            if matches > 0:
                # get the first document item only
                document_list_item = document_list.documentList.responseSet[0]
            elif search_context is not None:
                # failed to retrieve, get it without the search qualifier from last time.
                solr_query_spec.solrQuery.searchQ = "*:*"
                document_list, ret_status = opasPySolrLib.search_text_qs(solr_query_spec,
                                                                         session_info=session_info
                                                                         )
                matches = document_list.documentList.responseInfo.count
                if matches > 0:
                    # get the first document item only
                    document_list_item = document_list.documentList.responseSet[0]
                    # is user authorized?
                    if document_list.documentList.responseSet[0].accessLimited:
                        document_list.documentList.responseSet[0].document = document_list.documentList.responseSet[0].abstract
                    document_list.documentList.responseSet[0].term = f'SearchHits({search_context})'
                    document_list.documentList.responseSet[0].termCount = 0
    
        except Exception as e:
            logger.warning("get_document: No matches or error: %s", e)
            # return None
        else:
            if page_limit is None:
                page_limit = 100 # TODO - Check this (was 0 before)
            if page_offset is None:
                page_offset = 0
                
            response_info = document_list.documentList.responseInfo
            response_info.page=page
            response_info.limit = page_limit # use for page_limit, rather than the usual limit
            response_info.offset = page_offset # use for page_offset, rather than the usual limit
            # response_info.solrParams = solrParams
            # response_info.request = req_url
            
            if matches >= 1:
                # experimental options: uses option_flags to turn on
                if option_flags is not None:
                    if option_flags & opasConfig.OPTION_2_RETURN_TRANSLATION_SET:
                        # get document translations of the first document (note this also includes the original)
                        if document_list_item.origrx is not None:
                            translationSet, count = opasQueryHelper.quick_docmeta_docsearch(q_str=f"art_origrx:{document_list_item.origrx}", req_url=req_url)
                            if translationSet is not None:
                                document_list_item.translationSet = translationSet
                
                # is user authorized?
                if document_list.documentList.responseSet[0].accessLimited:
                    document_list.documentList.responseSet[0].document = document_list.documentList.responseSet[0].abstract
                    
                document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                                  responseSet = [document_list_item]
                                                                  )

                documents = models.Documents(documents = document_list_struct)

                ret_val = documents

    return ret_val

#-----------------------------------------------------------------------------
def documents_get_concordance_paras(para_lang_id,
                                    para_lang_rx=None, 
                                    solr_query_spec=None,
                                    ret_format="XML",
                                    req_url:str=None, 
                                    session_info=None
                                    ):
    """
    For non-authenticated users, this endpoint returns only Document summary information (summary/abstract)
    For authenticated users, it returns with the document itself

    >> resp = documents_get_concordance_paras("SEXixa5", ret_format="html") 

    >> resp = documents_get_concordance_paras("SEXixa5") 


    """
    ret_val = {}
    document_list = None
    if para_lang_rx is not None:
        paraLangFilterQ = f'({re.sub(",[]*", " || ", para_lang_rx)})'
    else:
        paraLangFilterQ = f"{para_lang_id}"
        
    query = "*:*"
    filterQ = f"para_lgrid:{paraLangFilterQ}"
    try:
        solr_query_spec = \
                opasQueryHelper.parse_to_query_spec(solr_query_spec=solr_query_spec, 
                                                    query=query,
                                                    filter_query=filterQ,
                                                    full_text_requested=True,
                                                    format_requested=ret_format,
                                                    return_field_set="CONCORDANCE", 
                                                    highlight_fields="para",
                                                    extra_context_len=opasConfig.SOLR_HIGHLIGHT_RETURN_FRAGMENT_SIZE, 
                                                    limit=1,
                                                    req_url=req_url
                                                    )

        document_list, ret_status = search_text_qs(solr_query_spec,
                                                   session_info=session_info
                                                   )

        matches = document_list.documentList.responseInfo.count
        if matches == 1:
            # get the first document item only
            document_list_item = document_list.documentList.responseSet[0]
            # is user authorized?
            if document_list.documentList.responseSet[0].accessLimited and 0:
                # Should we require it's authorized?
                document_list.documentList.responseSet[0].document = document_list.documentList.responseSet[0].abstract
            #else:
                ## All set
        else:
            logger.info(f"get_para_trans: No matches: {filterQ}")
    except Exception as e:
        logger.error(f"get_para_trans: No matches or error: {e}")
    else:
        if matches == 1:       
            document_list_struct = models.DocumentListStruct( responseInfo = document_list.documentList.responseInfo, 
                                                              responseSet = [document_list_item]
                                                              )

            documents = models.Documents(documents = document_list_struct)

            ret_val = documents

    return ret_val

#-----------------------------------------------------------------------------
def documents_get_glossary_entry(term_id,
                                 term_id_type=None, 
                                 retFormat="XML",
                                 req_url: str=None,
                                 session_info=None,
                                 limit=opasConfig.DEFAULT_LIMIT_FOR_DOCUMENT_RETURNS,
                                 offset=0):
    """
    For non-authenticated users, this endpoint should return an error (#TODO)

    For authenticated users, it returns with the glossary itself

    IMPORTANT NOTE: At least the way the database is currently populated, for a group, the textual part (text) is the complete group, 
      and thus the same for all entries.  This is best for PEP-Easy now, otherwise, it would need to concatenate all the result entries.
      
    As of 2020-11, Group and Name use text fields, so partial matches are included rather than string fields which require exact
     matches

    >> resp = documents_get_glossary_entry("ZBK.069.0001o.YN0019667860580", retFormat="html") 

    >> resp = documents_get_glossary_entry("ZBK.069.0001o.YN0004676559070") 

    >> resp = documents_get_glossary_entry("ZBK.069.0001e.YN0005656557260")


    """
    ret_val = {}

    # Name and Group are strings, and case sensitive, so search, as submitted, and uppercase as well
    if term_id_type == "Name":
        # 2020-11-11 use text field instead
        qstr = f'term_terms:("{term_id}")'
        # qstr = f'term:("{term_id}" || "{term_id.upper()}" || "{term_id.lower()}")'
    elif term_id_type == "Group":
        # 2020-11-11 use text field instead
        qstr = f'group_name_terms:("{term_id}")'
        # qstr = f'group_name:("{term_id}" || "{term_id.upper()}" || "{term_id.lower()}")'
    else: # default is term ID
        term_id = term_id.upper()
        qstr = f"term_id:{term_id} || group_id:{term_id}"

    solr_query_spec = \
            opasQueryHelper.parse_to_query_spec(query = f"art_id:{opasConfig.GLOSSARY_TOC_INSTANCE}",
                                                full_text_requested=False,
                                                abstract_requested=False,
                                                format_requested="XML",
                                                limit = 1,
                                                req_url = req_url
                                                )


    gloss_info, ret_status = search_text_qs(solr_query_spec, 
                                            extra_context_len=opasConfig.DEFAULT_KWIC_CONTENT_LENGTH,
                                            limit=1,
                                            session_info=session_info
                                            )
        
    gloss_template = gloss_info.documentList.responseSet[0]
    
    args = {
        "fl": opasConfig.GLOSSARY_ITEM_DEFAULT_FIELDS, 
        "facet.field": opasConfig.DOCUMENT_VIEW_FACET_LIST,
        "facet.mincount": 1
    }
    
    try:
        results = solr_gloss2.search(qstr, **args)
    except Exception as e:
        err = f"Solr query failed {e}"
        logger.error(err)
        raise Exception(err)
           
    document_item_list = []
    count = 0
    try:
        for result in results.docs:
            document = result.get("text", None)
            documentListItem = copy.copy(gloss_template)
            if not documentListItem.accessLimited:
                try:
                    if retFormat == "HTML":
                        document = opasxmllib.xml_str_to_html(document)
                    elif retFormat == "TEXTONLY":
                        document = opasxmllib.xml_elem_or_str_to_text(document)
                    else: # XML
                        document = document
                except Exception as e:
                    logger.warning(f"Error converting glossary content: {term_id} ({e})")
            else:
                try:
                    if retFormat == "HTML":
                        document = opasxmllib.xml_str_to_html(document, transformer_name=opasConfig.XSLT_XMLTOHTML_GLOSSARY_EXCERPT)
                    elif retFormat == "TEXTONLY":
                        document = opasxmllib.xml_elem_or_str_to_text(document)
                    else: # XML
                        document = document                   
                except ValidationError as e:
                    logger.error(e.json())  
                except Exception as e:
                    warning = f"Error getting contents of Glossary entry {term_id}"
                    logger.warning(warning)
                    document = warning
                
            documentListItem.term = result.get("term", None)
            documentListItem.document = document 
            documentListItem.groupName = result.get("group_name", None)
            documentListItem.groupTermCount = result.get("group_term_count", None)
            documentListItem.groupID = result.get("group_id", None)
            documentListItem.termSource = result.get("term_source", None)
            documentListItem.termType = result.get("term_type", None)
            # note, the rest of the document info is from the TOC instance, but we're changing the name here
            documentListItem.documentID = result.get("art_id", None)
            documentListItem.score = result.get("score", None)
            document_item_list.append(documentListItem)
            count = len(document_item_list)

    except IndexError as e:
        logger.warning("No matching glossary entry for %s.  Error: %s", (term_id, e))
    except KeyError as e:
        logger.warning("No content or abstract found for %s.  Error: %s", (term_id, e))
    else:
        response_info = models.ResponseInfo( count = count,
                                             fullCount = count,
                                             limit = limit,
                                             offset = offset,
                                             listType = "documentlist",
                                             fullCountComplete = True,
                                             request=f"{req_url}",
                                             timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                             )

        document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                          responseSet = document_item_list
                                                          )

        documents = models.Documents(documents = document_list_struct)

        ret_val = documents

    return ret_val

##-----------------------------------------------------------------------------
#def prep_document_download(document_id,
                           #session_info=None, 
                           #ret_format="HTML",
                           #base_filename="opasDoc",
                           #flex_fs=None):
    #"""
    #Preps a file in the right format for download.  Returns the filename of the prepared file and the status.
    #Note:
       #Checks access with the auth server via opasDocPerm.get_access_limitations
           #- If access not permitted, this returns an error (and None for the filename)
           #- If access allowed, it returns with the document itself

    #>> a = prep_document_download("IJP.051.0175A", ret_format="html") 

    #>> a = prep_document_download("IJP.051.0175A", ret_format="epub") 


    #"""
    #def add_epub_elements(str):
        ## for now, just return
        #return str

    #ret_val = None
    #status = httpCodes.HTTP_200_OK

    #q_str =  "art_id:%s" % (document_id)
    #logger.info(f"Solr Query: q={q_str}")
    #results = solr_docs.query( q = q_str,  
                               #fields = """art_id, art_citeas_xml, text_xml, art_excerpt, art_sourcetype, art_year,
                                           #art_sourcetitleabbr, art_vol, art_iss, art_pgrg, art_doi,
                                           #art_issn, file_classification"""
                             #)
    #try:
        #art_info = results.results[0]
        #docs = art_info.get("text_xml", art_info.get("art_excerpt", None))
    #except IndexError as e:
        #logger.warning("No matching document for %s.  Error: %s", document_id, e)
    #except KeyError as e:
        #logger.warning("No full-text content found for %s.  Error: %s", document_id, e)
    #else:
        #try:    
            #if isinstance(docs, list):
                #doc = docs[0]
            #else:
                #doc = docs
        #except Exception as e:
            #logger.warning("Empty return: %s", e)
        #else:
            #doi = art_info.get("art_doi", None)
            #pub_year = art_info.get("art_year", None)
            #file_classification = art_info.get("file_classification", None)
            
            #access = opasDocPerm.get_access_limitations( doc_id=document_id,
                                                         #classification=file_classification,
                                                         #session_info=session_info,
                                                         #year=pub_year,
                                                         #doi=doi,
                                                         #fulltext_request=True
                                                        #)
            #if access.accessLimited != True:
                #try:
                    #heading = opasxmllib.get_running_head( source_title=art_info.get("art_sourcetitleabbr", ""),
                                                           #pub_year=pub_year,
                                                           #vol=art_info.get("art_vol", ""),
                                                           #issue=art_info.get("art_iss", ""),
                                                           #pgrg=art_info.get("art_pgrg", ""),
                                                           #ret_format="HTML"
                                                           #)
    
                    #if ret_format.upper() == "HTML":
                        #html = opasxmllib.remove_encoding_string(doc)
                        #filename = opasxmllib.convert_xml_to_html_file(html, output_filename=document_id + ".html")  # returns filename
                        #ret_val = filename
                    #elif ret_format.upper() == "PDFORIG":
                        ## setup so can include year in path (folder names) in AWS, helpful.
                        #if flex_fs is not None:
                            #pub_year = art_info.get("art_year", None)
                            #filename = flex_fs.get_download_filename(filespec=document_id, path=localsecrets.PDF_ORIGINALS_PATH, year=pub_year, ext=".pdf")    
                            #ret_val = filename
                        #else:
                            #err_msg = "File path error."
                            #status = models.ErrorReturn( httpcode=httpCodes.HTTP_400_BAD_REQUEST,
                                                         #error_description=err_msg
                                                       #)
                            #ret_val = None
                    #elif ret_format.upper() == "PDF":
                        #pisa.showLogging() # debug only
                        #doc = opasxmllib.remove_encoding_string(doc)
                        #html_string = opasxmllib.xml_str_to_html(doc)
                        #html_string = re.sub("\[\[RunningHead\]\]", f"{heading}", html_string, count=1)
                        #html_string = re.sub("</html>", f"{COPYRIGHT_PAGE_HTML}</html>", html_string, count=1)                        
                        ## open output file for writing (truncated binary)
                        #filename = document_id + ".PDF" 
                        #result_file = open(filename, "w+b")
                        ## convert HTML to PDF
                        ## Need to fix links for graphics, e.g., see https://xhtml2pdf.readthedocs.io/en/latest/usage.html#using-xhtml2pdf-in-django
                        #pisaStatus = pisa.CreatePDF(src=html_string,            # the HTML to convert
                                                    #dest=result_file)           # file handle to receive result
                        ## close output file
                        #result_file.close()                 # close output file
                        ## return True on success and False on errors
                        #ret_val = filename
                    #elif ret_format.upper() == "EPUB":
                        #doc = opasxmllib.remove_encoding_string(doc)
                        #html_string = opasxmllib.xml_str_to_html(doc)
                        #html_string = re.sub("\[\[RunningHead\]\]", f"{heading}", html_string, count=1)
                        #html_string = add_epub_elements(html_string)
                        #filename = opasxmllib.html_to_epub(html_string, document_id, document_id)
                        #ret_val = filename
                    #else:
                        #err_msg = f"Format {ret_format} not supported"
                        #logger.warning(err_msg)
                        #ret_val = None
                        #status = models.ErrorReturn( httpcode=httpCodes.HTTP_400_BAD_REQUEST,
                                                     #error_description=err_msg
                                                   #)
    
                #except Exception as e:
                    #logger.warning("Can't convert data: %s", e)
                    #ret_val = None
                    #status = models.ErrorReturn( httpcode=httpCodes.HTTP_422_UNPROCESSABLE_ENTITY,
                                                 #error_description="Can't convert document data"
                                               #)
            #else:
                #status = models.ErrorReturn( httpcode=httpCodes.HTTP_401_UNAUTHORIZED,
                                             #error_description="No permission for document"
                                           #)
                #ret_val = None

    #return ret_val, status


##-----------------------------------------------------------------------------
#def get_kwic_list( marked_up_text, 
                   #extra_context_len=opasConfig.DEFAULT_KWIC_CONTENT_LENGTH, 
                   #solr_start_hit_tag=opasConfig.HITMARKERSTART, # supply whatever the start marker that solr was told to use
                   #solr_end_hit_tag=opasConfig.HITMARKEREND,     # supply whatever the end marker that solr was told to use
                   #output_start_hit_tag_marker=opasConfig.HITMARKERSTART_OUTPUTHTML, # the default output marker, in HTML
                   #output_end_hit_tag_marker=opasConfig.HITMARKEREND_OUTPUTHTML,
                   #limit=opasConfig.DEFAULT_MAX_KWIC_RETURNS
                   #):
    #"""
    #Find all nonoverlapping matches, using Solr's return.  Limit the number.

    #(See git version history for an earlier -- and different version)
    #"""

    #ret_val = []
    #em_marks = re.compile("(.{0,%s}%s.*%s.{0,%s})" % (extra_context_len, solr_start_hit_tag, solr_end_hit_tag, extra_context_len))
    #marked_up = re.compile(".*(%s.*%s).*" % (solr_start_hit_tag, solr_end_hit_tag))
    #marked_up_text = opasxmllib.xml_string_to_text(marked_up_text) # remove markup except match tags which shouldn't be XML

    #match_text_pattern = "({{.*?}})"
    #pat_compiled = re.compile(match_text_pattern)
    #word_list = pat_compiled.split(marked_up_text) # split all the words
    #index = 0
    #count = 0
    ##TODO may have problems with adjacent matches!
    #skip_next = False
    #for n in word_list:
        #if pat_compiled.match(n) and skip_next == False:
            ## we have a match
            #try:
                #text_before = word_list[index-1]
                #text_before_words = text_before.split(" ")[-extra_context_len:]
                #text_before_phrase = " ".join(text_before_words)
            #except:
                #text_before = ""
            #try:
                #text_after = word_list[index+1]
                #text_after_words = text_after.split(" ")[:extra_context_len]
                #text_after_phrase = " ".join(text_after_words)
                #if pat_compiled.search(text_after_phrase):
                    #skip_next = True
            #except:
                #text_after = ""

            ## change the tags the user told Solr to use to the final output tags they want
            ##   this is done to use non-xml-html hit tags, then convert to that after stripping the other xml-html tags
            #match = re.sub(solr_start_hit_tag, output_start_hit_tag_marker, n)
            #match = re.sub(solr_end_hit_tag, output_end_hit_tag_marker, match)

            #context_phrase = text_before_phrase + match + text_after_phrase

            #ret_val.append(context_phrase)

            #try:
                #logger.info("getKwicList Match: '...{}...'".format(context_phrase))
            #except Exception as e:
                #logger.error("getKwicList Error printing or logging matches. %s", e)

            #index += 1
            #count += 1
            #if count >= limit:
                #break
        #else:
            #skip_next = False
            #index += 1

    ## matchCount = len(ret_val)

    #return ret_val    
##-----------------------------------------------------------------------------
#def search_analysis( query_list, 
                     #filter_query = None,
                     ##more_like_these = False,
                     ##query_analysis = False,
                     #def_type = None,
                     ## summaryFields="art_id, art_sourcecode, art_vol, art_year, art_iss, 
                     ## art_iss_title, art_newsecnm, art_pgrg, art_title, art_author_id, art_citeas_xml", 
                     #summary_fields="art_id",                    
                     ## highlightFields='art_title_xml, abstract_xml, summaries_xml, art_authors_xml, text_xml', 
                     #full_text_requested=False, 
                     #user_logged_in=False,
                     #req_url:str=None, 
                     #limit=opasConfig.DEFAULT_MAX_KWIC_RETURNS,
                     #api_version="v2"
                     #):
    #"""
    #Analyze the search clauses in the query list
    #"""
    #ret_val = {}
    #return_item_list = []
    #rowCount = 0
    #term_field = None
    ## save classes to neutral names so we can change between documentList and termIndex
    #if 0: # api_version == "v1":
        #RetItem = models.DocumentListItem
        #RetStruct = models.DocumentListStruct
        #RetList = models.DocumentList
    #else:
        #RetItem = models.TermIndexItem
        #RetStruct = models.TermIndexStruct
        #RetList = models.TermIndex

    #for query_item in query_list:
        ## get rid of illegal stuff
        ## boolean_subs = [termpair.strip() for termpair in re.split("\s+\|\||\&\&|[ ]\s+", query_item)]
        ## boolean_subs = [termpair.strip() for termpair in re.split("\s*\|\||\&\&|AND|OR\s*", query_item)]
        ## for clause in query_item:
            ##clauses = n.split(":")
            ##if len(clauses) == 1:
                ##term_clause = clauses[0]
            ##else:
                ##field_clause = clauses[0]
                ##term_clause = clauses[1]
            ##subfield_clauses = shlex.split(term_clause)

        #try:
            #logger.info(f"Solr Query: q={query_item}")
            #results = solr_docs.query(query_item,
                                      #defType = def_type,
                                      #q_op="AND", 
                                      #queryAnalysis = True,
                                      #fields = summary_fields,
                                      #rows = 1,
                                      #start = 0)
        #except Exception as e:
            ## try to return an error message for now.
            ## logger.error(HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=e))
            ## raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Bad Search syntax")
            #return models.ErrorReturn(error="Search syntax error", error_description=f"There's an error in your input {e}")

        #if "!parent" in query_item:
            #term = query_item
            #try:
                #query_item = query_item.replace("parent_tag:(p_body || p_summaries || p_appxs)", "parent_tag:(doc)")
                #query_parsed = re.split("(&&|\|\|) \(", query_item)
                #del(query_parsed[0])
                #for i in range(len(query_parsed)):
                    #if query_parsed[i] in ["&&", "||"]:
                        #continue
                    #if "parent_tag" in query_parsed[i]:
                        #m = re.match(".*parent_tag:\((?P<parent_tag>.*)\).*?(?P<field>[A-z_]+)\:\((?P<terms>.*)\)\)?\)?", query_parsed[i])
                        #if m is not None:
                            #query_parsed[i] = m.groupdict(default="")
                            #query_parsed[i]['parent_tag'] = schemaMap.solr2user(query_parsed[i]['parent_tag'])
                            #query_parsed[i]['terms'] = query_parsed[i]['terms'].strip("()")

            #except Exception as e:
                #pass

            #by_parent = {}
            #connector = ""
            #for n in query_parsed:
                #if n == '&&':
                    #connector = " AND "
                    #continue
                #elif n == '||':
                    #connector = " OR "
                    #continue

                #try:
                    #by_parent[n["parent_tag"]] += f"{connector}{n['terms']}"
                #except KeyError as e:
                    #by_parent[n["parent_tag"]] = f"{n['terms']}"
                #except Exception as e:
                    #logger.warning(f"Error saving term clause: {e}")


            #for key, value in by_parent.items():
                #term = value
                #term_field = f"in same paragraph in {key}"

        #else:
            #term = query_item
            #if ":" in query_item:
                #try:
                    #term_field, term_value = query_item.split(":")
                #except:
                    ## pat = "((?P<parent>parent_tag\:\([a-z\s\(\)]\))\s+(AND|&&)\s+(?P<term>[A-z]+\:[\(\)A-Z]+))+"
                    ## too complex
                    #pass
                #else:
                    #term_value = opasQueryHelper.strip_outer_matching_chars(term_value, ")")
                    #term = f"{term_value} (in {schemaMap.FIELD2USER_MAP.get(term_field, term_field)})"
            #else:
                #term = opasQueryHelper.strip_outer_matching_chars(term, ")")
                #term = f"{query_item} (in text)"

        ##logger.debug("Analysis: Term %s, matches %s", field_clause, results._numFound)
        #item = RetItem(term = term, 
                       #termCount = results._numFound, 
                       #field=term_field
                       #)
        #return_item_list.append(item)
        #rowCount += 1

    ##if rowCount > 0:
        ##results = solr_docs.query(query_list,
                                    ##defType = def_type,
                                    ##q_op="AND", 
                                    ##queryAnalysis = True,
                                    ##fields = summary_fields,
                                    ##rows = 1,
                                    ##start = 0)

        ##item = models.DocumentListItem(term = "(combined)",
                                        ##termCount = results._numFound
                                        ##)
        ##document_item_list.append(item)
        ##rowCount += 1
        ##print ("Analysis: Term %s, matches %s" % ("combined: ", results._numFound))

    #response_info = models.ResponseInfo(count = rowCount,
                                        #fullCount = rowCount,
                                        #listType = "srclist",
                                        #fullCountComplete = True,
                                        #request=f"{req_url}",
                                        #timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)
                                        #)

    #response_info.count = len(return_item_list)

    #return_list_struct = RetStruct( responseInfo = response_info, 
                                    #responseSet = return_item_list
                                    #)
    #if 0: # api_version == "v1":
        #ret_val = RetList(documentList = return_list_struct)
    #else:
        #ret_val = RetList(termIndex = return_list_struct)


    #return ret_val
#-----------------------------------------------------------------------------
def get_term_count_list(term, term_field="text_xml", limit=opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, offset=0, term_order="index", wildcard_match_limit=4):
    """
    Returns a list of matching terms, and the number of articles with that term.

    Args:
        term (str): Term or comma separated list of terms to return data on.
        term_field (str): the text field to look in
        limit (int, optional): Paging mechanism, return is limited to this number of items.
        offset (int, optional): Paging mechanism, start with this item in limited return set, 0 is first item.
        term_order (str, optional): Return the list in this order, per Solr documentation.  Defaults to "index", which is the Solr determined indexing order.

    Returns:
        list of dicts with term, count and status var ret_status

        return ret_val, ret_status

    Docstring Tests:    
        >>> resp = get_term_count_list("Jealousy")

    """
    ret_val = {}
    ret_status = (200, "OK", "") # default is like HTTP_200_OK

    #  see if there is a wildcard
    if "," in term: 
        # It's a comma separated list!
        try:
            results = solr_docs_term_search( terms_fl=term_field,
                                             terms_list=term.lower(),
                                             terms_sort=term_order,  # index or count
                                             terms_mincount="1",
                                             #terms_ttf=True, 
                                             terms_limit=limit
                                             )
        except Exception as e:
            # ret_status = (e.httpcode, e.reason, e.body) # default is like HTTP_200_OK
            ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Search syntax error (Solr)", error_description=f"There's an error in your search input.")
        else:
            try:
                ret_val = results.terms.get(term_field, {})
            except Exception as e:
                logger.debug(f"get_term_count_list error: {e}")

    elif isinstance(term, list):
        for term_list_component in term:
            try:
                ret_val.update(get_term_count_list(term_list_component))
            except Exception as e:
                logger.debug(f"get_term_count_list error: {e}")

    elif re.match(".*[\*\?\.].*", term):
        # make sure legit
        # do subs to make wildcard * into zero or more regex character, and ? to zero or one
        term = re.sub("(?P<lead>[^\.])(?P<wildc>[\*\?])", "\g<lead>.\g<wildc>", term)
        try:
            re.compile(term)
            is_valid = True
        except:
            is_valid = False

        # #TODO test is_valid below
        try:
            results = solr_docs_term_search(terms_fl=term_field,
                                            terms_limit=wildcard_match_limit,
                                            terms_regex=term.lower(), # + ".*",
                                            terms_mincount="1",
                                            terms_sort="count"  # wildcard, pick highest
                                            )
        except solr.SolrException as e:
            # ret_status = (e.httpcode, e.reason, e.body) # default is like HTTP_200_OK
            ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Search syntax error (Solr)", error_description=f"There's an error in your search input.")

        try:
            ret_val = results.terms.get(term_field, {})
            term_wild = term.replace(".", "")
            ret_val = {f"{key}({term_wild})": value for (key, value) in ret_val.items()}
            ret_val.update({f"Total({term_wild})>=":sum(x for x in ret_val.values())})

        except Exception as e:
            logger.debug(f"get_term_count_list error: {e}")
    else:
        # Note: we need an exact match here.
        try:
            results = solr_docs_term_search( terms_fl=term_field,
                                             terms_prefix=term.lower(),
                                             terms_sort=term_order,  # index or count
                                             terms_mincount="1",
                                             #terms_ttf=True, 
                                             terms_limit=1 # only one response needed
                                             )
        except solr.SolrException as e:
            # ret_status = (e.httpcode, e.reason, e.body) # default is like HTTP_200_OK
            ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Search syntax error (Solr)", error_description=f"There's an error in your search input.")
        else:
            try:
                ret_val = results.terms.get(term_field, {})
            except Exception as e:
                logger.debug(f"get_term_count_list error: {e}")

    return ret_val

##-----------------------------------------------------------------------------
#def get_term_index(term_partial,
                   #term_field="text",
                   #core="docs",
                   #req_url:str=None, 
                   #limit=opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS,
                   #offset=0,
                   #order="index"):
    #"""
    #Returns a list of matching terms from an arbitrary field in the Solr docs database, using the /terms search handler

    #Args:
        #term_partial (str): String prefix of author names to return.
        #term_field (str): Where to look for term
        #limit (int, optional): Paging mechanism, return is limited to this number of items.
        #offset (int, optional): Paging mechanism, start with this item in limited return set, 0 is first item.
        #order (str, optional): Return the list in this order, per Solr documentation.  Defaults to "index", which is the Solr determined indexing order.

    #Returns:
        #models.termIndex: Pydantic structure (dict) for termIndex.  See models.py

    #Docstring Tests:    
        #>>> resp = get_term_index("love", term_field="art_kwds_str", limit=5)
        #>>> resp.termIndex.responseSet[0].termCount > 0
        #True
        #>>> resp = get_term_index("bion", term_field="art_kwds", limit=5)
        #>>> resp.termIndex.responseSet[0].termCount > 0
        #True
        #>>> resp = get_term_index("will", term_field="text", limit=5)
        #>>> resp.termIndex.responseSet[0].termCount > 0
        #True
        #>>> resp = get_term_index("david", term_field="art_authors_mast", limit=5)
        #>>> resp.termIndex.responseSet[0].termCount > 0
        #True
        #>>> resp = get_term_index("Inter.*", term_field="art_sourcetitlefull", limit=5)
        #>>> resp.termIndex.responseSet[0].termCount > 0
        #True
        #>>> resp = get_term_index("pand", limit=20)
        #>>> resp.termIndex.responseSet[0].termCount > 0
        #True
        #>>> resp = get_term_index("pand.*", limit=5)
        #>>> resp.termIndex.responseSet[0].termCount > 0
        #True
    #"""
    #ret_val = {}

    #core_term_indexers = {
        #"docs": solr_docs_term_search,
        #"authors": solr_authors_term_search,
    #}

    #try:
        #term_index = core_term_indexers[core]
    #except:
        ## error
        #logger.error("Specified core does not have a term index configured")
    #else:
        #if "*" in term_partial or "?" in term_partial or "." in term_partial:
            #results = term_index( terms_fl=term_field,
                                  #terms_regex=term_partial.lower() + ".*",
                                  #terms_limit=limit,  
                                  #terms_sort=order  # index or count
                                  #)           
        #else:
            #results = term_index( terms_fl=term_field,
                                  #terms_prefix=term_partial.lower(),
                                  #terms_sort=order,  # index or count
                                  #terms_limit=limit
                                  #)

        #response_info = models.ResponseInfo( limit=limit,
                                             #offset=offset,
                                             #listType="termindex",
                                             #core=core, 
                                             #scopeQuery=[f"Terms: {term_partial}"],
                                             #solrParams=results._params,
                                             #request=f"{req_url}",
                                             #timeStamp=datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)
                                             #)

        #term_index_items = []
        #for key, value in results.terms[term_field].items():
            #if value > 0:
                #item = models.TermIndexItem(term = key, 
                                            #field = term_field,
                                            #termCount = value,
                                            #) 
                #term_index_items.append(item)
                #logger.debug ("TermIndexInfo", item)

        #response_info.count = len(term_index_items)
        #response_info.fullCountComplete = limit >= response_info.count

        #term_index_struct = models.TermIndexStruct( responseInfo = response_info, 
                                                    #responseSet = term_index_items
                                                    #)

        #term_index = models.TermIndex(termIndex = term_index_struct)

        #ret_val = term_index

    #return ret_val

#================================================================================================================
def save_opas_session_cookie(request: Request, response: Response, session_id):
    ret_val = False
    already_set = False
    if session_id is not None and session_id is not 'None':
        already_set = False
        try:
            opasSession = [x for x in response.raw_headers[0] if b"opasSessionID" in x]
            already_set = b"opasSessionID" in opasSession[0][0:13]
        except Exception as e:
            logger.debug(f"Ok, opasSessionID not in response {e}")

    if already_set == False and session_id is not None:
        try:
            logger.debug("Saved OpasSessionID Cookie")
            response.set_cookie(
                opasConfig.OPASSESSIONID,
                value=f"{session_id}",
                domain=localsecrets.COOKIE_DOMAIN
            )
            ret_val = True
        except Exception as e:
            logger.error(f"Can't save opas session-id cookie: {e}")
            ret_val = False
            
    return ret_val
    

#================================================================================================================
def search_stats_for_download(solr_query_spec: models.SolrQuerySpec,
                              limit=None,
                              offset=None,
                              sort=None, 
                              session_info=None,
                              solr_core="pepwebdocs"
                              ):
    """
    SPECIAL - do the search for the purpose of downloading stat...could be many records.
    
    """
    ret_val = {}
    ret_status = (200, "OK") # default is like HTTP_200_OK
    
    if solr_query_spec.solrQueryOpts is None: # initialize a new model
        solr_query_spec.solrQueryOpts = models.SolrQueryOpts()

    if solr_query_spec.solrQuery is None: # initialize a new model
        solr_query_spec.solrQuery = models.SolrQuery()

    solr_query_spec.solrQueryOpts.hlMaxAnalyzedChars = 200
    # let this be None, if no limit is set.
    if offset is not None:
        solr_query_spec.offset = offset

    if limit is not None:
        solr_query_spec.limit = min(limit, opasConfig.MAX_DOCUMENT_RECORDS_RETURNED_AT_ONCE) 
    else:
        solr_query_spec.limit = 99000 # opasConfig.MAX_DOCUMENT_RECORDS_RETURNED_AT_ONCE

    if sort is not None:
        solr_query_spec.solrQuery.sort = sort

    # q must be part of any query; this appears to be the cause of the many solr syntax errors seen. 
    if solr_query_spec.solrQuery.searchQ is None or solr_query_spec.solrQuery.searchQ == "":
        logger.error(f">>>>>> solr_query_spec.solrQuery.searchQ is {solr_query_spec.solrQuery.searchQ}.  Filter: {solr_query_spec.solrQuery.filterQ} The endpoint request was: {req_url}")
        solr_query_spec.solrQuery.searchQ = "*.*"

    try:
        solr_param_dict = { 
                            "q": solr_query_spec.solrQuery.searchQ,
                            "fq": solr_query_spec.solrQuery.filterQ,
                            "q_op": solr_query_spec.solrQueryOpts.qOper, 
                            "debugQuery": solr_query_spec.solrQueryOpts.queryDebug or localsecrets.SOLR_DEBUG,
                            # "defType" : solr_query_spec.solrQueryOpts.defType,
                            "fl" : opasConfig.DOCUMENT_ITEM_STAT_FIELDS, 
                            "rows" : solr_query_spec.limit,
                            "start" : solr_query_spec.offset,
                            "sort" : solr_query_spec.solrQuery.sort
        }
    except Exception as e:
        logger.error(f"Solr Param Assignment Error {e}")

    #allow core parameter here
    solr_query_spec.core = "pepwebdocs"
    solr_core = solr_docs

    # ############################################################################
    # SOLR Download Query
    # ############################################################################
    try:
        start_time = time.time()
        results = solr_core.query(**solr_param_dict)
        total_time = time.time() - start_time
    except solr.SolrException as e:
        if e is None:
            ret_val = models.ErrorReturn(httpcode=httpCodes.HTTP_400_BAD_REQUEST, error="Solr engine returned an unknown error", error_description=f"Solr engine returned error without a reason")
            logger.error(f"Solr Runtime Search Error: {e.reason}")
            logger.error(e.body)
        elif e.reason is not None:
            ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Solr engine returned an unknown error", error_description=f"Solr engine returned error {e.httpcode} - {e.reason}")
            logger.error(f"Solr Runtime Search Error: {e.reason}")
            logger.error(e.body)
        else:
            ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Search syntax error", error_description=f"There's an error in your input (no reason supplied)")
            logger.error(f"Solr Runtime Search Error: {e.httpcode}")
            logger.error(e.body)
        
        ret_status = (e.httpcode, e) # e has type <class 'solrpy.core.SolrException'>, with useful elements of httpcode, reason, and body, e.g.,

    else: #  search was ok
        try:
            logger.info("Download Search Performed: %s", solr_query_spec.solrQuery.searchQ)
            logger.info("The Filtering: %s", solr_query_spec.solrQuery.filterQ)
            logger.info("Result  Set Size: %s", results._numFound)
            logger.info("Return set limit: %s", solr_query_spec.limit)
            logger.info(f"Download Stats Solr Search Time: {total_time}")
            scopeofquery = [solr_query_spec.solrQuery.searchQ, solr_query_spec.solrQuery.filterQ]
    
            if ret_status[0] == 200: 
                documentItemList = []
                rowCount = 0
                for result in results.results:
                    documentListItem = models.DocumentListItem()
                    #documentListItem = get_base_article_info_from_search_result(result, documentListItem)
                    citeas = result.get("art_citeas_xml", None)
                    citeas = opasQueryHelper.force_string_return_from_various_return_types(citeas)
                    
                    documentListItem.score = result.get("score", None)               
                    # see if this article is an offsite article
                    result["text_xml"] = None                   
                    stat = {}
                    count_all = result.get("art_cited_all", None)
                    if count_all is not None:
                        stat["art_cited_5"] = result.get("art_cited_5", None)
                        stat["art_cited_10"] = result.get("art_cited_10", None)
                        stat["art_cited_20"] = result.get("art_cited_20", None)
                        stat["art_cited_all"] = count_all
    
                    count0 = result.get("art_views_lastcalyear", 0)
                    count1 = result.get("art_views_lastweek", 0)
                    count2 = result.get("art_views_last1mos", 0)
                    count3 = result.get("art_views_last6mos", 0)
                    count4 = result.get("art_views_last12mos", 0)
    
                    if count0 + count1 + count2 + count3+ count4 > 0:
                        stat["art_views_lastcalyear"] = count0
                        stat["art_views_lastweek"] = count1
                        stat["art_views_last1mos"] = count2
                        stat["art_views_last6mos"] = count3
                        stat["art_views_last12mos"] = count4
    
                    if stat == {}:
                        stat = None
    
                    documentListItem.stat = stat
                    documentListItem.docLevel = result.get("art_level", None)
                    rowCount += 1
                    # add it to the set!
                    documentItemList.append(documentListItem)

            responseInfo = models.ResponseInfo(
                                               count = len(results.results),
                                               fullCount = results._numFound,
                                               totalMatchCount = results._numFound,
                                               limit = solr_query_spec.limit,
                                               offset = solr_query_spec.offset,
                                               listType="documentlist",
                                               scopeQuery=[scopeofquery], 
                                               fullCountComplete = solr_query_spec.limit >= results._numFound,
                                               solrParams = results._params,
                                               request=f"{solr_query_spec.urlRequest}",
                                               core=solr_query_spec.core, 
                                               timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
            )
    
            documentListStruct = models.DocumentListStruct( responseInfo = responseInfo, 
                                                            responseSet = documentItemList
                                                            )
    
            documentList = models.DocumentList(documentList = documentListStruct)
    
            ret_val = documentList
            
        except Exception as e:
            logger.error(f"problem with query {e}")
            
    logger.info(f"Download Stats Document Return Time: {time.time() - start_time}")
    return ret_val, ret_status

##================================================================================================================
#def submit_file(submit_token: bytes, xml_data: bytes, pdf_data: bytes): 
    #pass

# -------------------------------------------------------------------------------------------------------
# run it (tests)!

if __name__ == "__main__":
    sys.path.append('./config') 

    print (40*"*", "opasAPISupportLib Tests", 40*"*")
    print ("Running in Python %s" % sys.version_info[0])
    logger = logging.getLogger(__name__)
    # extra logging for standalong mode 
    logger.setLevel(logging.WARN)
    # create console handler and set level to debug
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARN)
    # create formatter
    formatter = logging.Formatter('%(asctime)s %(name)s %(lineno)d - %(levelname)s %(message)s')    
    # add formatter to ch
    ch.setFormatter(formatter)
    # add ch to logger
    logger.addHandler(ch)

    import doctest
    doctest.testmod(optionflags=doctest.ELLIPSIS|doctest.NORMALIZE_WHITESPACE)
    print ("All tests complete!")
    print ("Fini")
