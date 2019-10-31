#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=C0321,C0103,C0301,E1101,C0303,E1004,C0330,R0915,R0914,W0703,C0326

"""
opasAPISupportLib

This library is meant to hold the heart of the API based Solr queries and other support 
functions.  

2019.0614.1 - Python 3.7 compatible.  Work in progress.

"""
__author__      = "Neil R. Shapiro"
__copyright__   = "Copyright 2019, Psychoanalytic Electronic Publishing"
__license__     = "Apache 2.0"
__version__     = "2019.0714.1"
__status__      = "Development"

import os
import os.path
import sys
sys.path.append('./solrpy')
# print(os.getcwd())
import http.cookies
import re
import secrets
from starlette.responses import JSONResponse, Response
from starlette.requests import Request
from starlette.responses import Response
import time
import datetime
from datetime import datetime, timedelta
from typing import Union, Optional, Tuple, List
from enum import Enum
# import pymysql

import opasConfig
from localsecrets import BASEURL, SOLRURL, SOLRUSER, SOLRPW, DEBUG_DOCUMENTS, CONFIG, COOKIE_DOMAIN
from opasConfig import OPASSESSIONID, OPASACCESSTOKEN, OPASEXPIRES 
from stdMessageLib import COPYRIGHT_PAGE_HTML  # copyright page text to be inserted in ePubs and PDFs

if (sys.version_info > (3, 0)):
    # Python 3 code in this block
    from io import StringIO
    pyVer = 3
else:
    # Python 2 code in this block
    pyVer = 2
    import StringIO
    
import solrpy as solr
import lxml
import logging
logger = logging.getLogger(__name__)

from lxml import etree
from pydantic import BaseModel
from pydantic import ValidationError

from ebooklib import epub              # for HTML 2 EPUB conversion
from xhtml2pdf import pisa             # for HTML 2 PDF conversion

# note: documents and documentList share the same internals, except the first level json label (documents vs documentlist)
import models

import opasXMLHelper as opasxmllib
import opasGenSupportLib as opasgenlib
import opasCentralDBLib
import sourceInfoDB as SourceInfoDB
    
sourceDB = SourceInfoDB.SourceInfoDB()

#from solrq import Q
import json

# Setup a Solr instance. The timeout is optional.
#solr = pysolr.Solr('http://localhost:8983/solr/pepwebproto', timeout=10)
#This is the old way -- should switch to class Solr per https://pythonhosted.org/solrpy/reference.html
if SOLRUSER is not None:
    solr_docs = solr.Solr(SOLRURL + 'pepwebdocs', http_user=SOLRUSER, http_pass=SOLRPW)
    solr_refs = solr.SolrConnection(SOLRURL + 'pepwebrefs', http_user=SOLRUSER, http_pass=SOLRPW)
    solr_gloss = solr.SolrConnection(SOLRURL + 'pepwebglossary', http_user=SOLRUSER, http_pass=SOLRPW)
    solr_authors = solr.SolrConnection(SOLRURL + 'pepwebauthors', http_user=SOLRUSER, http_pass=SOLRPW)
    solr_author_term_search = solr.SearchHandler(solr_authors, "/terms")

else:
    solr_docs = solr.SolrConnection(SOLRURL + 'pepwebdocs')
    solr_refs = solr.SolrConnection(SOLRURL + 'pepwebrefs')
    solr_gloss = solr.SolrConnection(SOLRURL + 'pepwebglossary')
    solr_authors = solr.SolrConnection(SOLRURL + 'pepwebauthors')
    solr_author_term_search = solr.SearchHandler(solr_authors, "/terms")

#API endpoints
documentURL = "/v1/Documents/"
TIME_FORMAT_STR = '%Y-%m-%dT%H:%M:%SZ'

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
                     access_token=None,
                     expires_time=None, 
                     keep_active=False,
                     force_new_session=False,
                     user=None):
    """
    Get session info from cookies, or create a new session if one doesn't exist.
    Return a sessionInfo object with all of that info, and a database handle
    
    """
    session_id = get_session_id(request)
    logger.debug("Get Session Info, Session ID via GetSessionID: %s", session_id)
    
    if session_id is None or session_id=='' or force_new_session:  # we need to set it
        # get new sessionID...even if they already had one, this call forces a new one
        logger.debug("session_id is none (or forcedNewSession).  We need to start a new session.")
        ocd, session_info = start_new_session(response, request, access_token, keep_active=keep_active, user=user)  
        
    else: # we already have a session_id, no need to recreate it.
        # see if an access_token is already in cookies
        access_token = get_access_token(request)
        expiration_time = get_expiration_time(request)
        logger.debug(f"session_id {session_id} is already set.")
        try:
            ocd = opasCentralDBLib.opasCentralDB(session_id, access_token, expiration_time)
            session_info = ocd.get_session_from_db(session_id)
            if session_info is None:
                # this is an error, and means there's no recorded session info.  Should we create a s
                #  session record, return an error, or ignore? #TODO
                # try creating a record
                username="NotLoggedIn"
                ret_val, session_info = ocd.save_session(session_id, 
                                                         userID=0,
                                                         userIP=request.client.host, 
                                                         connectedVia=request.headers["user-agent"],
                                                         username=username
                                                        )  # returns save status and a session object (matching what was sent to the db)

        except ValidationError as e:
            logger.error("Validation Error: %s", e.json())             
    
    logger.debug("getSessionInfo: %s", session_info)
    return ocd, session_info
    
def is_session_authenticated(request: Request, resp: Response):
    """
    Look to see if the session has been marked authenticated in the database
    """
    ocd, sessionInfo = get_session_info(request, resp)
    # sessionID = sessionInfo.session_id
    # is the user authenticated? if so, loggedIn is true
    ret_val = sessionInfo.authenticated
    return ret_val
    
def extract_html_fragment(html_str, xpath_to_extract="//div[@id='abs']"):
    # parse HTML
    htree = etree.HTML(html_str)
    ret_val = htree.xpath(xpath_to_extract)
    # make sure it's a string
    ret_val = force_string_return_from_various_return_types(ret_val)
    
    return ret_val

#-----------------------------------------------------------------------------
def start_new_session(resp: Response, request: Request, session_id=None, access_token=None, keep_active=None, user=None):
    """
    Create a new session record and set cookies with the session

    Returns database object, and the sessionInfo object
    
    If user is supplied, that means they've been authenticated.
      
    This should be the only place to generate and start a new session.
    """
    logger.debug("************** Starting a new SESSION!!!! *************")
    # session_start=datetime.utcfromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
    max_age = get_max_age(keep_active)
    token_expiration_time=datetime.utcfromtimestamp(time.time() + max_age) # .strftime('%Y-%m-%d %H:%M:%S')
    if session_id == None:
        session_id = secrets.token_urlsafe(16)
        logger.info("startNewSession assigning New Session ID: {}".format(session_id))

    # Try 
    # set_cookies(resp, session_id, access_token, token_expires_time=token_expiration_time)
    # get the database Object
    ocd = opasCentralDBLib.opasCentralDB()
    # save the session info
    if user:
        username=user.username
        ret_val, sessionInfo = ocd.save_session(session_id=session_id, 
                                                username=user.username,
                                                userID=user.user_id,
                                                expiresTime=token_expiration_time,
                                                userIP=request.client.host, 
                                                connectedVia=request.headers["user-agent"],
                                                accessToken = access_token
                                                )
    else:
        username="NotLoggedIn"
        ret_val, sessionInfo = ocd.save_session(session_id, 
                                                userID=0,
                                                expiresTime=token_expiration_time,
                                                userIP=request.client.host, 
                                                connectedVia=request.headers["user-agent"],
                                                username=username)  # returns save status and a session object (matching what was sent to the db)

    # return the object so the caller can get the details of the session
    return ocd, sessionInfo

#-----------------------------------------------------------------------------
def delete_cookies(resp: Response, session_id=None, access_token=None):
    """
    Delete the session and or accessToken cookies in the response header 
   
    """

    logger.debug("Setting specified cookies to empty to delete them")
    expires = datetime.utcnow()
    if session_id is not None:
        set_cookie(resp, OPASSESSIONID, value=None, domain=COOKIE_DOMAIN, path="/", expires=expires, max_age=0)

    if access_token is not None:
        set_cookie(resp, OPASACCESSTOKEN, value=None, domain=COOKIE_DOMAIN, path="/", expires=expires, max_age=0)
    return resp
    
##-----------------------------------------------------------------------------
#def set_cookies(resp: Response, session_id, access_token=None, max_age=None, token_expires_time=None):
    #"""
    #Set the session and or accessToken cookies in the response header 
    
    #if accessToken isn't supplied, it is not set.
    
    #"""
    
    #logger.debug("Setting cookies for {}".format(COOKIE_DOMAIN))
    #if session_id is not None:
        #logger.debug("Session Cookie being Written from SetCookies")
        #set_cookie(resp, OPASSESSIONID, session_id, domain=COOKIE_DOMAIN, expires=token_expires_time, httponly=False)

    #if access_token is not None:
        #access_token = access_token.decode("utf-8")
        #set_cookie(resp, OPASACCESSTOKEN, access_token, domain=COOKIE_DOMAIN, httponly=False, expires=token_expires_time, max_age=max_age) 

    #return resp
    
#-----------------------------------------------------------------------------
#def parse_cookies_from_header(request):
    #ret_val = {}
    #client_supplied_cookies = request.headers.get("cookie", None)
    #if client_supplied_cookies is not None:
        #cookie_statements = client_supplied_cookies.split(";")
        #for n in cookie_statements:
            #cookie, value = n.split("=")
            #ret_val[cookie] = value

    #return ret_val

#-----------------------------------------------------------------------------
def get_session_id(request):
    ret_val = request.cookies.get(OPASSESSIONID, None)
    
    #if ret_val is None:
        #cookie_dict = parse_cookies_from_header(request)
        #ret_val = cookie_dict.get(OPASSESSIONID, None)
        #if ret_val is not None:
            #logger.debug("getSessionID: Session cookie had to be retrieved from header: {}".format(ret_val))
    #else:
        #logger.debug ("getSessionID: Session cookie from client: {}".format(ret_val))
    return ret_val

#-----------------------------------------------------------------------------
def get_access_token(request):
    ret_val = request.cookies.get(opasConfig.OPASACCESSTOKEN, None)
    return ret_val

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

#-----------------------------------------------------------------------------
def force_string_return_from_various_return_types(text_str, min_length=5):
    """
    Sometimes the return isn't a string (it seems to often be "bytes") 
      and depending on the schema, from Solr it can be a list.  And when it
      involves lxml, it could even be an Element node or tree.
      
    This checks the type and returns a string, converting as necessary.
    
    >>> force_string_return_from_various_return_types(["this is really a list",], min_length=5)
    'this is really a list'

    """
    ret_val = None
    if text_str is not None:
        if isinstance(text_str, str):
            if len(text_str) > min_length:
                # we have an abstract
                ret_val = text_str
        elif isinstance(text_str, list):
            ret_val = text_str[0]
            if ret_val == [] or ret_val == '[]':
                ret_val = None
        else:
            logger.error("Type mismatch on Solr Data. forceStringReturn ERROR: %s", type(ret_val))

        try:
            if isinstance(ret_val, lxml.etree._Element):
                ret_val = etree.tostring(ret_val)
            
            if isinstance(ret_val, bytes) or isinstance(ret_val, bytearray):
                logger.error("Byte Data")
                ret_val = ret_val.decode("utf8")
        except Exception as e:
            err = "forceStringReturn Error forcing conversion to string: %s / %s" % (type(ret_val), e)
            logger.error(err)
            
    return ret_val        

#-----------------------------------------------------------------------------
def get_article_data_raw(article_id, fields=None):  # DEPRECATED??????? (at least, not used)
    """
    Fetch an article "Doc" from the Solr solrDocs core.  If fields is none, it fetches all fields.

    This returns a dictionary--the one returned by Solr 
      (hence why the function is Raw rather than Pydantic like getArticleData)
      
    >>> result = get_article_data_raw("APA.009.0331A")
    >>> result["art_id"]
    'APA.009.0331A'
    
    """
    ret_val = None
    if article_id != "":
        try:
            results = solr_docs.query(q = "art_id:{}".format(article_id),  fields = fields)
        except Exception as e:
            logger.error("Solr Error: {}".format(e))
            ret_val = None
        else:
            if results._numFound == 0:
                ret_val = None
            else:
                ret_val = results.results[0]

    return ret_val
                
#-----------------------------------------------------------------------------
def get_article_data(article_id, fields=None):  # DEPRECATED???????  (at least, not used)
    """
    Fetch an article "Doc" from the Solr solrDocs core.  If fields is none, it fetches all fields.

    Returns the pydantic model object for a document in a regular documentListStruct

    >>> result = get_article_data("APA.009.0331A")
    >>> result.documentList.responseSet[0].documentID
    'APA.009.0331A'
    
    """
    ret_val = None
    if article_id != "":
        try:
            results = solr_docs.query(q = "art_id:{}".format(article_id),  fields = fields)
        except Exception as e:
            logger.error("Solr Error: {}".format(e))
            ret_val = None
        else:
            if results._numFound == 0:
                ret_val = None
            else:
                ret_val = results.results[0]
    limit = 5 # for now, we may make this 1
    offset = 0
    response_info = models.ResponseInfo (count = len(results.results),
                                         fullCount = results._numFound,
                                         totalMatchCount = results._numFound,
                                         limit = limit,
                                         offset = offset,
                                         listType="documentlist",
                                         scopeQuery=None,
                                         fullCountComplete = limit >= results._numFound,
                                         solrParams = results._params,
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                       )

    document_item_list = []
    row_count = 0
    # row_offset = 0
    for result in results.results:
        author_ids = result.get("art_authors", None)
        if author_ids is None:
            authorMast = None
        else:
            authorMast = opasgenlib.deriveAuthorMast(author_ids)

        pgrg = result.get("art_pgrg", None)
        if pgrg is not None:
            pg_start, pg_end = opasgenlib.pgrg_splitter(pgrg)
         
        # TODO: Highlighting return is incomplete.  Return from non-highlighted results, and figure out workaround later.
        
        document_id = result.get("art_id", None)        
        #titleXml = results.highlighting[documentID].get("art_title_xml", None)
        title_xml = result.get("art_title_xml", None)
        title_xml = force_string_return_from_various_return_types(title_xml)
        #abstractsXml = results.highlighting[documentID].get("abstracts_xml", None)
        abstracts_xml = result.get("abstracts_xml", None)
        abstracts_xml  = force_string_return_from_various_return_types(abstracts_xml )
        #summariesXml = results.highlighting[documentID].get("abstracts_xml", None)
        summaries_xml = result.get("abstracts_xml", None)
        summaries_xml  = force_string_return_from_various_return_types(summaries_xml)
        #textXml = results.highlighting[documentID].get("text_xml", None)
        text_xml = result.get("text_xml", None)
        text_xml  = force_string_return_from_various_return_types(text_xml)
        kwic_list = []
        kwic = ""  # this has to be "" for PEP-Easy, or it hits an object error.  
    
        if DEBUG_DOCUMENTS != 1:
            if not user_logged_in or not full_text_requested:
                text_xml = get_excerpt_from_abs_sum_or_doc(xml_abstract=abstracts_xml,
                                                           xml_summary=summaries_xml,
                                                           xml_document=text_xml
                                                          )

        citeas = result.get("art_citeas_xml", None)
        citeas = force_string_return_from_various_return_types(citeas)
        
        try:
            item = models.DocumentListItem(PEPCode = result.get("art_pepsrccode", None), 
                                           year = result.get("art_year", None),
                                           vol = result.get("art_vol", None),
                                           pgRg = pgrg,
                                           pgStart = pg_start,
                                           pgEnd = pg_end,
                                           authorMast = authorMast,
                                           documentID = document_id,
                                           documentRefHTML = citeas,
                                           documentRef = opasxmllib.xml_elem_or_str_to_text(citeas, default_return=""),
                                           title = title_xml,
                                           abstract = abstracts_xml,
                                           documentText = None, #textXml,
                                           score = result.get("score", None), 
                                           )
        except ValidationError as e:
            logger.error(e.json())  
        else:
            row_count += 1
            # logger.debug("{}:{}".format(row_count, citeas))
            document_item_list.append(item)
            if row_count > limit:
                break

    response_info.count = len(document_item_list)
    
    document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                      responseSet = document_item_list
                                                    )
    
    document_list = models.DocumentList(documentList = document_list_struct)
    
    ret_val = document_list
    
    return ret_val

#-----------------------------------------------------------------------------
def database_get_most_downloaded(period: str="all",
                                document_type: str="journals",
                                author: str=None,
                                title: str=None,
                                journal_name: str=None,
                                limit: int=5,
                                offset=0):
    """
    Return the most downloaded (viewed) journal articles duing the prior period years.
    
    Args:
        period (int or str, optional): Look only at articles this many years back to current.  Defaults to 5.
        documentType (str, optional): The type of document, enumerated set: journals, books, videos, or all.  Defaults to "journals"
        author (str, optional): Filter, include matching author names per string .  Defaults to None (no filter).
        title (str, optional): Filter, include only titles that match.  Defaults to None (no filter).
        journalName (str, optional): Filter, include only journals matching this name.  Defaults to None (no filter).
        limit (int, optional): Paging mechanism, return is limited to this number of items.
        offset (int, optional): Paging mechanism, start with this item in limited return set, 0 is first item.

    Returns:
        models.DocumentList: Pydantic structure (dict) for DocumentList.  See models.py

    Docstring Tests:
    
    >>> result = database_get_most_downloaded()
    DocumentListItem PEPCode='IJP' sourceTitle=None documentID='IJP.077.0217A' authormast=None documentRef='Fonagy, P. and Target, M. (1996). Playing With Reality: I. Theory Of Mind And…' documentRefHTML='<p class="citeas"><span class="authors">Fonagy, P. and Target, M.</span> (<sp…' kwicList=None kwic=None issue='' issueTitle=None newSectionName=None pgRg='217-233' pgStart='217' pgEnd='233' title='Int. J. Psychoanal.' vol='77' year='1996' term=None termCount=None abstract=None document=None updated=None accessLimited=False accessLimitedReason=None accessLimitedDescription=None accessLimitedCurrentContent=None score=None rank=None instanceCount=24 count1=24 count2=24 count3=24 count4=24 count5=0 countAll=None similarDocs=None similarMaxScore=None similarNumFound=None
    DocumentListItem PEPCode='APA' sourceTitle=None documentID='APA.014.0243A' authormast=None documentRef='Kohut, H. (1966). Forms and Transformations of Narcissism. Journal of the Ame…' documentRefHTML='<p class="citeas"><span class="authors">Kohut, H.</span> (<span class="year">…' kwicList=None kwic=None issue='' issueTitle=None newSectionName=None pgRg='243-272' pgStart='243' pgEnd='272' title='J. Amer. Psychoanal. Assn.' vol='14' year='1966' term=None termCount=None abstract=None document=None updated=None accessLimited=False accessLimitedReason=None accessLimitedDescription=None accessLimitedCurrentContent=None score=None rank=None instanceCount=10 count1=0 count2=0 count3=10 count4=10 count5=0 countAll=None similarDocs=None similarMaxScore=None similarNumFound=None
    DocumentListItem PEPCode='IJPSP' sourceTitle=None documentID='IJPSP.009.0324A' authormast=None documentRef='Strozier, C., Strug, D., Pinteris, K. and Kelley, K. (2014). On Dreams. Inter…' documentRefHTML='<p class="citeas"><span class="authors">Strozier, C., Strug, D., Pinteris, K.…' kwicList=None kwic=None issue='4' issueTitle=None newSectionName=None pgRg='324-338' pgStart='324' pgEnd='338' title='Int. J. Psychoanal. Self Psychol.' vol='9' year='2014' term=None termCount=None abstract=None document=None updated=None accessLimited=False accessLimitedReason=None accessLimitedDescription=None accessLimitedCurrentContent=None score=None rank=None instanceCount=8 count1=8 count2=8 count3=8 count4=8 count5=0 countAll=None similarDocs=None similarMaxScore=None similarNumFound=None
    DocumentListItem PEPCode='PI' sourceTitle=None documentID='PI.037.0425A' authormast=None documentRef='Orange, D. M. (2017). From Fallibilism to Clinical Humility: Brothers and Cor…' documentRefHTML='<p class="citeas"><span class="authors">Orange, D. M.</span> (<span class="ye…' kwicList=None kwic=None issue='6' issueTitle=None newSectionName=None pgRg='425-428' pgStart='425' pgEnd='428' title='Psychoanal. Inq.' vol='37' year='2017' term=None termCount=None abstract=None document=None updated=None accessLimited=False accessLimitedReason=None accessLimitedDescription=None accessLimitedCurrentContent=None score=None rank=None instanceCount=7 count1=5 count2=5 count3=7 count4=7 count5=0 countAll=None similarDocs=None similarMaxScore=None similarNumFound=None
    DocumentListItem PEPCode='APA' sourceTitle=None documentID='APA.011.0576A' authormast=None documentRef='Arlow, J. A. (1963). The Supervisory Situation. Journal of the American Psych…' documentRefHTML='<p class="citeas"><span class="authors">Arlow, J. A.</span> (<span class="yea…' kwicList=None kwic=None issue='' issueTitle=None newSectionName=None pgRg='576-594' pgStart='576' pgEnd='594' title='J. Amer. Psychoanal. Assn.' vol='11' year='1963' term=None termCount=None abstract=None document=None updated=None accessLimited=False accessLimitedReason=None accessLimitedDescription=None accessLimitedCurrentContent=None score=None rank=None instanceCount=6 count1=0 count2=0 count3=6 count4=6 count5=0 countAll=None similarDocs=None similarMaxScore=None similarNumFound=None

    >>> result.documentList.responseSet[0].documentID
    'IJP.077.0217A'

    """
    if period.lower() not in ['5', '10', '20', 'all']:
        period = '5'

    ocd = opasCentralDBLib.opasCentralDB()
    count, most_downloaded = ocd.get_most_downloaded( view_period=period, 
                                                      document_type=document_type, 
                                                      author=author, 
                                                      title=title, 
                                                      journal_name=journal_name, 
                                                      limit=limit, offset=offset
                                                    )  # (most viewed)
    
    response_info = models.ResponseInfo( count = count,
                                         fullCount = count,
                                         limit = limit,
                                         offset = offset,
                                         listType="mostviewed",
                                         fullCountComplete = limit >= count,  # technically, inaccurate, but there's no point
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                       )

    
    document_list_items = []
    row_count = 0

    for download in most_downloaded:
        hdg_author = download.get("hdgauthor", None)
        hdg_title = download.get("hdgtitle", None)
        src_title = download.get("srctitleseries", None)
        volume = download.get("vol", None)
        issue = download.get("issue", "")
        year = download.get("pubyear", None)
        pgrg = download.get("pgrg", None)
        pg_start, pg_end = opasgenlib.pgrg_splitter(pgrg)
        xmlref = download.get("xmlref", None)
        citeas = opasxmllib.get_html_citeas( authors_bib_style=hdg_author, 
                                              art_year=year,
                                              art_title=hdg_title, 
                                              art_pep_sourcetitle_full=src_title, 
                                              art_vol=volume, 
                                              art_pgrg=pgrg
                                            )

        item = models.DocumentListItem( documentID = download.get("documentid", None),
                                        instanceCount = download.get("last12months", None),
                                        title = download.get("srctitleseries", None),
                                        PEPCode = download.get("jrnlcode", None), 
                                        authorMast = download.get("authorMast", None),
                                        year = download.get("pubyear", None),
                                        vol = download.get("vol", None),
                                        pgRg = download.get("pgrg", None),
                                        issue = issue,
                                        pgStart = pg_start,
                                        pgEnd = pg_end,
                                        count1 = download.get("lastweek", None),
                                        count2 = download.get("lastmonth", None),
                                        count3 = download.get("last6months", None),
                                        count4 = download.get("last12months", None),
                                        count5 = download.get("lastcalyear", None),
                                        documentRefHTML = citeas,
                                        documentRef = opasxmllib.xml_elem_or_str_to_text(xmlref, default_return=None),
                                     ) 
        row_count += 1
        logger.debug(item)
        document_list_items.append(item)
        if row_count > limit:
            break

    # Not sure why it doesn't come back sorted...so we sort it here.
    #ret_val2 = sorted(ret_val, key=lambda x: x[1], reverse=True)
    
    response_info.count = len(document_list_items)
    
    document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                      responseSet = document_list_items
                                                    )
    
    document_list = models.DocumentList(documentList = document_list_struct)
    
    ret_val = document_list
    
    return ret_val   


#-----------------------------------------------------------------------------
def database_get_most_cited(period: models.TimePeriod='5',
                            limit: int=10,
                            offset: int=0):
    """
    Return the most cited journal articles duing the prior period years.
    
    period must be either '5', 10, '20', or 'all'
    
    >>> result = database_get_most_cited()
    databaseGetMostCited Number found: 114935
    >>> result.documentList.responseSet[0].documentID
    'IJP.027.0099A'

    """
    if str(period).lower() not in models.TimePeriod._value2member_map_:
        period = '5'
    
    results = solr_docs.query( q = "*:*",  
                               fl = f"art_id, title, art_vol, art_iss, art_year,  art_pepsrccode, \
                                     art_cited_{period}, art_cited_all, timestamp, art_pepsrccode, \
                                     art_pepsourcetype, art_pepsourcetitleabbr, art_pgrg, \
                                     art_citeas_xml, art_authors_mast, abstract_xml, text_xml",
                               fq = "art_pepsourcetype: journal",
                               sort = f"art_cited_{period} desc",
                               rows = limit, offset = offset
                              )

    logger.debug("databaseGetMostCited Number found: %s", results._numFound)
    
    response_info = models.ResponseInfo( count = len(results.results),
                                         fullCount = results._numFound,
                                         limit = limit,
                                         offset = offset,
                                         listType ="mostcited",
                                         fullCountComplete = limit >= results._numFound,
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR) 
                                       )

    
    document_list_items = []
    row_count = 0
    # row_offset = 0

    for result in results:
        PEPCode = result.get("art_pepsrccode", None)
        # volume = result.get("art_vol", None)
        # issue = result.get("art_iss", "")
        # year = result.get("art_year", None)
        # abbrev = result.get("art_pepsourcetitleabbr", "")
        # updated = result.get("timestamp", None)
        # updated = updated.strftime('%Y-%m-%d')
        pgrg = result.get("art_pgrg", None)
        pg_start, pg_end = opasgenlib.pgrg_splitter(pgrg)
        
        #displayTitle = abbrev + " v%s.%s (%s) (Added: %s)" % (volume, issue, year, updated)
        #volumeURL = "/v1/Metadata/Contents/%s/%s" % (PEPCode, issue)
        
        citeas = result.get("art_citeas_xml", None)
        art_abstract = result.get("art_abstract", None)
        
        item = models.DocumentListItem( documentID = result.get("art_id", None),
                                        instanceCount = result.get(f"art_cited_{period}", None),
                                        title = result.get("art_pepsourcetitlefull", ""),
                                        PEPCode = PEPCode, 
                                        authorMast = result.get("art_authors_mast", None),
                                        year = result.get("art_year", None),
                                        vol = result.get("art_vol", None),
                                        issue = result.get("art_iss", ""),
                                        pgRg = pgrg,
                                        pgStart = pg_start,
                                        pgEnd = pg_end,
                                        documentRefHTML = citeas,
                                        documentRef = opasxmllib.xml_elem_or_str_to_text(citeas, default_return=None),
                                        abstract = art_abstract
                                      ) 
        row_count += 1
        document_list_items.append(item)
        if row_count > limit:
            break

    # Not sure why it doesn't come back sorted...so we sort it here.
    #ret_val2 = sorted(ret_val, key=lambda x: x[1], reverse=True)
    
    response_info.count = len(document_list_items)
    
    document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                      responseSet = document_list_items
                                                    )
    
    document_list = models.DocumentList(documentList = document_list_struct)
    
    ret_val = document_list
    
    return ret_val   

#-----------------------------------------------------------------------------
def database_get_whats_new(days_back=7, limit=opasConfig.DEFAULT_LIMIT_FOR_WHATS_NEW, offset=0):
    """
    Return a what's been updated in the last week
    
    >>> result = database_get_whats_new()
    databaseWhatsNew Number found: 0
    databaseWhatsNew Expanded search to most recent...Number found: 73
    """    
    
    try:
        results = solr_docs.query(q = f"timestamp:[NOW-{days_back}DAYS TO NOW]",  
                                 fl = "art_id, title, art_vol, art_iss, art_pepsrccode, timestamp, art_pepsourcetype",
                                 fq = "{!collapse field=art_pepsrccode max=art_year_int}",
                                 sort="timestamp", sort_order="desc",
                                 rows=limit, offset=0,
                                 )
    
        logger.debug("databaseWhatsNew Number found: %s", results._numFound)
    except Exception as e:
        logger.error(f"Solr Search Exception: {e}")
    
    if results._numFound == 0:
        try:
            results = solr_docs.query( q = "art_pepsourcetype:journal",  
                                       fl = "art_id, title, art_vol, art_iss, art_pepsrccode, timestamp, art_pepsourcetype",
                                       fq = "{!collapse field=art_pepsrccode max=art_year_int}",
                                       sort="timestamp", sort_order="desc",
                                       rows=limit, offset=0,
                                     )
    
            logger.debug("databaseWhatsNew Expanded search to most recent...Number found: %s", results._numFound)

        except Exception as e:
            logger.error(f"Solr Search Exception: {e}")
    
    response_info = models.ResponseInfo( count = len(results.results),
                                         fullCount = results._numFound,
                                         limit = limit,
                                         offset = offset,
                                         listType="newlist",
                                         fullCountComplete = limit >= results._numFound,
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                       )

    
    whats_new_list_items = []
    row_count = 0
    already_seen = []
    for result in results:
        PEPCode = result.get("art_pepsrccode", None)
        #if PEPCode is None or PEPCode in ["SE", "GW", "ZBK", "IPL"]:  # no books
            #continue
        src_type = result.get("art_pepsourcetype", None)
        if src_type != "journal":
            continue
            
        volume = result.get("art_vol", None)
        issue = result.get("art_iss", "")
        year = result.get("art_year", None)
        abbrev = sourceDB.sourceData[PEPCode].get("sourcetitleabbr", "")
        updated = result.get("timestamp", None)
        updated = updated.strftime('%Y-%m-%d')
        display_title = abbrev + " v%s.%s (%s) " % (volume, issue, year)
        if display_title in already_seen:
            continue
        else:
            already_seen.append(display_title)
        volume_url = "/v1/Metadata/Contents/%s/%s" % (PEPCode, issue)
        src_title = sourceDB.sourceData[PEPCode].get("sourcetitlefull", "")
            
        item = models.WhatsNewListItem( documentID = result.get("art_id", None),
                                        displayTitle = display_title,
                                        abbrev = abbrev,
                                        volume = volume,
                                        issue = issue,
                                        year = year,
                                        PEPCode = PEPCode, 
                                        srcTitle = src_title,
                                        volumeURL = volume_url,
                                        updated = updated
                                     ) 
        whats_new_list_items.append(item)
        row_count += 1
        if row_count > limit:
            break

    response_info.count = len(whats_new_list_items)
    
    whats_new_list_struct = models.WhatsNewListStruct( responseInfo = response_info, 
                                                       responseSet = whats_new_list_items
                                                     )
    
    ret_val = models.WhatsNewList(whatsNew = whats_new_list_struct)
    
    return ret_val   # WhatsNewList

#-----------------------------------------------------------------------------
def search_like_the_pep_api():
    pass  # later

#-----------------------------------------------------------------------------
def metadata_get_volumes(pep_code, year="*", limit=opasConfig.DEFAULT_LIMIT_FOR_VOLUME_LISTS, offset=0):
    """
    Get a list of volumes for this pep_code.
    
    #TODO: Not currently used in OPAS server though.  Deprecate?
    
    """
    ret_val = []
           
    results = solr_docs.query( q = "art_pepsrccode:%s && art_year:%s" % (pep_code, year),  
                               fields = "art_vol, art_year",
                               sort="art_year", sort_order="asc",
                               fq="{!collapse field=art_vol}",
                               rows=limit, start=offset
                             )

    logger.debug("metadataGetVolumes Number found: %s", results._numFound)
    response_info = models.ResponseInfo( count = len(results.results),
                                         fullCount = results._numFound,
                                         limit = limit,
                                         offset = offset,
                                         listType="volumelist",
                                         fullCountComplete = limit >= results._numFound,
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                       )

    volume_item_list = []
    for result in results.results:
        item = models.VolumeListItem( PEPCode = pep_code, 
                                      year = result.get("art_year", None),
                                      vol = result.get("art_vol", None),
                                      score = result.get("score", None)
                                    )
    
        #logger.debug(item)
        volume_item_list.append(item)
       
    response_info.count = len(volume_item_list)
    
    volume_list_struct = models.VolumeListStruct( responseInfo = response_info, 
                                                  responseSet = volume_item_list
                                                )
    
    volume_list = models.VolumeList(volumeList = volume_list_struct)
    
    ret_val = volume_list
    return ret_val

#-----------------------------------------------------------------------------
def metadata_get_contents(pep_code, #  e.g., IJP, PAQ, CPS
                          year="*",
                          vol="*",
                          limit=opasConfig.DEFAULT_LIMIT_FOR_CONTENTS_LISTS, offset=0):
    """
    Return a jounals contents
    
    >>> metadata_get_contents("IJP", "1993", limit=5, offset=0)
    <DocumentList documentList=<DocumentListStruct responseInfo=<ResponseInfo count=5 limit=5 offset=0 page=No…>
    >>> metadata_get_contents("IJP", "1993", limit=5, offset=5)
    <DocumentList documentList=<DocumentListStruct responseInfo=<ResponseInfo count=5 limit=5 offset=5 page=No…>
    """
    ret_val = []
    if year == "*" and vol != "*":
        # specified only volume
        field="art_vol"
        search_val = vol
    else:  #Just do year
        field="art_year"
        search_val = "*"
        
    results = solr_docs.query(q = "art_pepsrccode:{} && {}:{}".format(pep_code, field, search_val),  
                             fields = "art_id, art_vol, art_year, art_iss, art_iss_title, art_newsecnm, art_pgrg, art_title, art_author_id, art_citeas_xml",
                             sort="art_year, art_pgrg", sort_order="asc",
                             rows=limit, start=offset
                             )

    response_info = models.ResponseInfo( count = len(results.results),
                                         fullCount = results._numFound,
                                         limit = limit,
                                         offset = offset,
                                         listType="documentlist",
                                         fullCountComplete = limit >= results._numFound,
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                       )

    document_item_list = []
    for result in results.results:
        # transform authorID list to authorMast
        authorIDs = result.get("art_author_id", None)
        if authorIDs is None:
            authorMast = None
        else:
            authorMast = opasgenlib.deriveAuthorMast(authorIDs)
        
        pgRg = result.get("art_pgrg", None)
        pgStart, pgEnd = opasgenlib.pgrg_splitter(pgRg)
        citeAs = result.get("art_citeas_xml", None)  
        citeAs = force_string_return_from_various_return_types(citeAs)
        
        item = models.DocumentListItem(PEPCode = pep_code, 
                                year = result.get("art_year", None),
                                vol = result.get("art_vol", None),
                                pgRg = result.get("art_pgrg", None),
                                pgStart = pgStart,
                                pgEnd = pgEnd,
                                authorMast = authorMast,
                                documentID = result.get("art_id", None),
                                documentRef = opasxmllib.xml_elem_or_str_to_text(citeAs, default_return=""),
                                documentRefHTML = citeAs,
                                score = result.get("score", None)
                                )
        #logger.debug(item)
        document_item_list.append(item)

    response_info.count = len(document_item_list)
    
    document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                      responseSet=document_item_list
                                                    )
    
    document_list = models.DocumentList(documentList = document_list_struct)
    
    ret_val = document_list
    
    return ret_val

#-----------------------------------------------------------------------------
def metadata_get_videos(src_type=None, pep_code=None, limit=opasConfig.DEFAULT_LIMIT_FOR_METADATA_LISTS, offset=0):
    """
    Fill out a sourceInfoDBList which can be used for a getSources return, but return individual 
      videos, as is done for books.  This provides more information than the 
      original API which returned video "journals" names.  
      
    """
    
    if pep_code != None:
        query = "art_pepsourcetype:video* AND art_pepsrccode:{}".format(pep_code)
    else:
        query = "art_pepsourcetype:video*"
    try:
        srcList = solr_docs.query(q = query,  
                                  fields = "art_id, art_issn, art_pepsrccode, art_authors, title, \
                                            art_pepsourcetitlefull, art_pepsourcetitleabbr, art_vol, \
                                            art_year, art_citeas_xml, art_lang, art_pgrg",
                                  sort = "art_citeas_xml",
                                  sort_order = "asc",
                                  rows=limit, start=offset
                                 )
    except Exception as e:
        logger.error("metadataGetVideos Error: {}".format(e))

    source_info_dblist = []
    # count = len(srcList.results)
    total_count = int(srcList.results.numFound)
    
    for result in srcList.results:
        source_info_record = {}
        authors = result.get("art_authors")
        if authors is None:
            source_info_record["author"] = None
        elif len(authors) > 1:
            source_info_record["author"] = "; ".join(authors)
        else:    
            source_info_record["author"] = authors[0]
            
        source_info_record["src_code"] = result.get("art_pepsrccode")
        source_info_record["ISSN"] = result.get("art_issn")
        source_info_record["documentID"] = result.get("art_id")
        try:
            source_info_record["title"] = result.get("title")[0]
        except:
            source_info_record["title"] = ""
            
        source_info_record["art_citeas"] = result.get("art_citeas_xml")
        source_info_record["pub_year"] = result.get("art_year")
        source_info_record["bib_abbrev"] = result.get("art_year")
        try:
            source_info_record["language"] = result.get("art_lang")[0]
        except:
            source_info_record["language"] = "EN"

        logger.debug("metadataGetVideos: %s", source_info_record)
        source_info_dblist.append(source_info_record)

    return total_count, source_info_dblist

#-----------------------------------------------------------------------------
def metadata_get_source_by_type(src_type=None, src_code=None, limit=opasConfig.DEFAULT_LIMIT_FOR_METADATA_LISTS, offset=0):
    """
    Return a list of source metadata, by type (e.g., journal, video, etc.).
    
    No attempt here to map to the correct structure, just checking what field/data items we have in sourceInfoDB.
    
    >>> returnData = metadata_get_source_by_type(src_type="journal", limit=3)
    MetadataGetSourceByType: Number found: 3

    >>> returnData = metadata_get_source_by_type(src_type="book", limit=3)
    MetadataGetSourceByType: Number found: 3

    >>> returnData = metadata_get_source_by_type(src_type="journals", limit=5, offset=0)
    MetadataGetSourceByType: Number found: 5
    
    >>> returnData = metadata_get_source_by_type(src_type="journals", limit=5, offset=6)
    MetadataGetSourceByType: Number found: 5
    
    """
    ret_val = []
    source_info_dblist = []
    ocd = opasCentralDBLib.opasCentralDB()
    # standardize Source type, allow plural, different cases, but code below this part accepts only those three.
    src_type = src_type.lower()
    if src_type not in ["journal", "book"]:
        if re.match("videos.*", src_type, re.IGNORECASE):
            src_type = "videos"
        elif re.match("video", src_type, re.IGNORECASE):
            src_type = "videostream"
        elif re.match("boo.*", src_type, re.IGNORECASE):
            src_type = "book"
        else: # default
            src_type = "journal"
   
    # This is not part of the original API, it brings back individual videos rather than the videostreams
    # but here in case we need it.  In that case, your source must be videos.*, like videostream, in order
    # to load individual videos rather than the video journals
    if src_type == "videos":
        #  gets count of videos and a list of them (from Solr database)
        total_count, source_info_dblist = metadata_get_videos(src_type, src_code, limit, offset)
        count = len(source_info_dblist)
    else: # get from mySQL
        try:
            if src_code != "*":
                total_count, sourceData = ocd.get_sources(src_type = src_type, source=src_code, limit=limit, offset=offset)
            else:
                total_count, sourceData = ocd.get_sources(src_type = src_type, limit=limit, offset=offset)
                
            for sourceInfoDict in sourceData:
                if sourceInfoDict["src_type"] == src_type:
                    # match
                    source_info_dblist.append(sourceInfoDict)
            if limit < total_count:
                count = limit
            else:
                count = total_count
            logger.debug("MetadataGetSourceByType: Number found: %s", count)
        except Exception as e:
            errMsg = "MetadataGetSourceByType: Error getting source information.  {}".format(e)
            count = 0
            logger.error(errMsg)

    response_info = models.ResponseInfo( count = count,
                                         fullCount = total_count,
                                         fullCountComplete = count == total_count,
                                         limit = limit,
                                         offset = offset,
                                         listLabel = "{} List".format(src_type),
                                         listType = "sourceinfolist",
                                         scopeQuery = "*",
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                       )

    source_info_listitems = []
    counter = 0
    for source in source_info_dblist:
        counter += 1
        if counter < offset:
            continue
        if counter > limit:
            break
        try:
            title = source.get("title")
            authors = source.get("author")
            pub_year = source.get("pub_year")
            publisher = source.get("publisher")
            bookCode = None
            if src_type == "book":
                bookCode = source.get("base_code")
                m = re.match("(?P<code>[a-z]+)(?P<num>[0-9]+)", bookCode, re.IGNORECASE)
                if m is not None:
                    code = m.group("code")
                    num = m.group("num")
                    bookCode = code + "." + num
                
                art_citeas = u"""<p class="citeas"><span class="authors">%s</span> (<span class="year">%s</span>) <span class="title">%s</span>. <span class="publisher">%s</span>.""" \
                    %                   (authors,
                                         source.get("pub_year"),
                                         title,
                                         publisher
                                        )
            elif src_type == "video":
                art_citeas = source.get("art_citeas")
            else:
                art_citeas = title # journals just should show display title


            try:
                item = models.SourceInfoListItem( sourceType = src_type,
                                                  PEPCode = source.get("src_code"),
                                                  authors = authors,
                                                  pub_year = pub_year,
                                                  documentID = source.get("art_id"),
                                                  displayTitle = art_citeas,
                                                  title = title,
                                                  srcTitle = title,  # v1 Deprecated for future
                                                  bookCode = bookCode,
                                                  abbrev = source.get("bib_abbrev"),
                                                  bannerURL = f"http://{BASEURL}/{opasConfig.IMAGES}/banner{source.get('src_code')}.logo.gif",
                                                  language = source.get("language"),
                                                  ISSN = source.get("ISSN"),
                                                  yearFirst = source.get("start_year"),
                                                  yearLast = source.get("end_year"),
                                                  embargoYears = source.get("embargo_yrs")
                                                ) 
                #logger.debug("metadataGetSourceByType SourceInfoListItem: %s", item)
            except ValidationError as e:
                logger.error("metadataGetSourceByType SourceInfoListItem Validation Error:")
                logger.error(e.json())        

        except Exception as e:
                logger.error("metadataGetSourceByType: %s", e)        
            

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

#-----------------------------------------------------------------------------
def metadata_get_source_by_code(src_code=None, limit=opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, offset=0):
    """
    Rather than get this from Solr, where there's no 1:1 records about this, we will get this from the sourceInfoDB instance.
    
    No attempt here to map to the correct structure, just checking what field/data items we have in sourceInfoDB.
    
    The sourceType is listed as part of the endpoint path, but I wonder if we should really do this 
    since it isn't needed, the pepCodes are unique.
    
    curl -X GET "http://stage.pep.gvpi.net/api/v1/Metadata/Journals/AJP/" -H "accept: application/json"
    
    >>> ret = metadata_get_source_by_code(src_code="APA")
    metadataGetSourceByCode: Number found: 1
    >>> metadata_get_source_by_code()
    metadataGetSourceByCode: Number found: 191
    <SourceInfoList sourceInfo=<SourceInfoStruct responseInfo=<ResponseInfo count=191 limit=10 offset=0 page=N…>
    
    """
    ret_val = []
    ocd = opasCentralDBLib.opasCentralDB()
    
    # would need to add URL for the banner
    if src_code is not None:
        total_count, source_info_dblist = ocd.get_sources(src_code)    #sourceDB.sourceData[pepCode]
        #sourceType = sourceInfoDBList.get("src_type", None)
    else:
        total_count, source_info_dblist = ocd.get_sources(src_code)    #sourceDB.sourceData
        #sourceType = "All"
            
    count = len(source_info_dblist)
    logger.debug("metadataGetSourceByCode: Number found: %s", count)

    response_info = models.ResponseInfo( count = count,
                                         fullCount = total_count,
                                         limit = limit,
                                         offset = offset,
                                         #listLabel = "{} List".format(sourceType),
                                         listType = "sourceinfolist",
                                         scopeQuery = "*",
                                         fullCountComplete = True,
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                       )

    source_info_list_items = []
    counter = 0
    for source in source_info_dblist:
        counter += 1
        if counter < offset:
            continue
        if counter > limit:
            break
        try:
            # remove leading and trailing spaces from strings in response.
            source = {k:v.strip() if isinstance(v, str) else v for k, v in source.items()}
            item = models.SourceInfoListItem( ISSN = source.get("ISSN"),
                                              PEPCode = source.get("src_code"),
                                              abbrev = source.get("bib_abbrev"),
                                              bannerURL = f"http://{BASEURL}/{opasConfig.IMAGES}/banner{source.get('src_code')}.logo.gif",
                                              displayTitle = source.get("title"),
                                              language = source.get("language"),
                                              yearFirst = source.get("start_year"),
                                              yearLast = source.get("end_year"),
                                              sourceType = source.get("src_type"),
                                              title = source.get("title")
                                            ) 
        except ValidationError as e:
            logger.info("metadataGetSourceByCode: SourceInfoListItem Validation Error:")
            logger.error(e.json())

        source_info_list_items.append(item)
        
    try:
        source_info_struct = models.SourceInfoStruct( responseInfo = response_info, 
                                                      responseSet = source_info_list_items
                                                    )
    except ValidationError as e:
        logger.info("metadataGetSourceByCode: SourceInfoStruct Validation Error:")
        logger.error(e.json())
    
    try:
        source_info_list = models.SourceInfoList(sourceInfo = source_info_struct)
    
    except ValidationError as e:
        logger.info("metadataGetSourceByCode: SourceInfoList Validation Error:")
        logger.error(e.json())
    
    ret_val = source_info_list
    return ret_val

#-----------------------------------------------------------------------------
def authors_get_author_info(author_partial, limit=opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, offset=0, author_order="index"):
    """
    Returns a list of matching names (per authors last name), and the number of articles in PEP found by that author.
    
    Args:
        author_partial (str): String prefix of author names to return.
        limit (int, optional): Paging mechanism, return is limited to this number of items.
        offset (int, optional): Paging mechanism, start with this item in limited return set, 0 is first item.
        author_order (str, optional): Return the list in this order, per Solr documentation.  Defaults to "index", which is the Solr determined indexing order.

    Returns:
        models.DocumentList: Pydantic structure (dict) for DocumentList.  See models.py

    Docstring Tests:    
        >>> resp = authors_get_author_info("Tuck")
        authorsGetAuthorInfo AuthorIndexItem authorID='tucker, landrum' publicationsURL='/v1/Authors/Publications/tucker, landrum/' publicationsCount=1
        authorsGetAuthorInfo AuthorIndexItem authorID='tucker, nicholas' publicationsURL='/v1/Authors/Publications/tucker, nicholas/' publicationsCount=1
        authorsGetAuthorInfo AuthorIndexItem authorID='tucker, robert c.' publicationsURL='/v1/Authors/Publications/tucker, robert c./' publicationsCount=1
        authorsGetAuthorInfo AuthorIndexItem authorID='tucker, sara s.' publicationsURL='/v1/Authors/Publications/tucker, sara s./' publicationsCount=7
        authorsGetAuthorInfo AuthorIndexItem authorID='tucker, susan' publicationsURL='/v1/Authors/Publications/tucker, susan/' publicationsCount=1
        authorsGetAuthorInfo AuthorIndexItem authorID='tucker, william m.' publicationsURL='/v1/Authors/Publications/tucker, william m./' publicationsCount=1
        authorsGetAuthorInfo AuthorIndexItem authorID='tuckett, david' publicationsURL='/v1/Authors/Publications/tuckett, david/' publicationsCount=63
        >>> resp.authorIndex.responseInfo.count
        7
        >>> resp = authors_get_author_info("Levins.*", limit=5)
        authorsGetAuthorInfo AuthorIndexItem authorID='levinsky-wohl, mina' publicationsURL='/v1/Authors/Publications/levinsky-wohl, mina/' publicationsCount=5
        authorsGetAuthorInfo AuthorIndexItem authorID='levinson, alice' publicationsURL='/v1/Authors/Publications/levinson, alice/' publicationsCount=1
        authorsGetAuthorInfo AuthorIndexItem authorID='levinson, dorthy m.' publicationsURL='/v1/Authors/Publications/levinson, dorthy m./' publicationsCount=4
        authorsGetAuthorInfo AuthorIndexItem authorID='levinson, gordon' publicationsURL='/v1/Authors/Publications/levinson, gordon/' publicationsCount=6
        authorsGetAuthorInfo AuthorIndexItem authorID='levinson, harry' publicationsURL='/v1/Authors/Publications/levinson, harry/' publicationsCount=2
        >>> resp.authorIndex.responseInfo.count
        5
    """
    ret_val = {}
    method = 2
    
    if method == 1:
        query = "art_author_id:/%s.*/" % (author_partial)
        results = solr_authors.query( q=query,
                                      fields="authors, art_author_id",
                                      facet_field="art_author_id",
                                      facet="on",
                                      facet_sort="index",
                                      facet_prefix="%s" % author_partial,
                                      facet_limit=limit,
                                      facet_offset=offset,
                                      rows=0
                                    )       

    if method == 2:
        # should be faster way, but about the same measuring tuck (method1) vs tuck.* (method2) both about 2 query time.  However, allowing regex here.
        if "*" in author_partial or "?" in author_partial or "." in author_partial:
            results = solr_author_term_search( terms_fl="art_author_id",
                                               terms_limit=limit,  # this causes many regex expressions to fail
                                               terms_regex=author_partial.lower() + ".*",
                                               terms_sort=author_order  # index or count
                                              )           
        else:
            results = solr_author_term_search( terms_fl="art_author_id",
                                               terms_prefix=author_partial.lower(),
                                               terms_sort=author_order,  # index or count
                                               terms_limit=limit
                                             )
    
    response_info = models.ResponseInfo( limit=limit,
                                         offset=offset,
                                         listType="authorindex",
                                         scopeQuery="Terms: %s" % author_partial,
                                         solrParams=results._params,
                                         timeStamp=datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)
                                       )
    
    author_index_items = []
    if method == 1:
        for key, value in results.facet_counts["facet_fields"]["art_author_id"].items():
            if value > 0:
                item = models.AuthorIndexItem(authorID = key, 
                                              publicationsURL = "/v1/Authors/Publications/{}/".format(key),
                                              publicationsCount = value,
                                             ) 
                author_index_items.append(item)
                logger.debug ("authorsGetAuthorInfo", item)

    if method == 2:  # faster way
        for key, value in results.terms["art_author_id"].items():
            if value > 0:
                item = models.AuthorIndexItem(authorID = key, 
                                              publicationsURL = "/v1/Authors/Publications/{}/".format(key),
                                              publicationsCount = value,
                                             ) 
                author_index_items.append(item)
                logger.debug("authorsGetAuthorInfo: %s", item)
       
    response_info.count = len(author_index_items)
    response_info.fullCountComplete = limit >= response_info.count
        
    author_index_struct = models.AuthorIndexStruct( responseInfo = response_info, 
                                                    responseSet = author_index_items
                                                  )
    
    author_index = models.AuthorIndex(authorIndex = author_index_struct)
    
    ret_val = author_index
    return ret_val

#-----------------------------------------------------------------------------
def authors_get_author_publications(author_partial, limit=opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, offset=0):
    """
    Returns a list of publications (per authors partial name), and the number of articles by that author.
    
    >>> resp = authors_get_author_publications(author_partial="Tuck")
    Author Publications: Number found: 0
    Author Publications: Query didn't work - art_author_id:/Tuck/
    Author Publications: trying again - art_author_id:/Tuck[ ]?.*/
    Author Publications: Number found: 72
    >>> resp = authors_get_author_publications(author_partial="Fonag")
    Author Publications: Number found: 0
    Author Publications: Query didn't work - art_author_id:/Fonag/
    Author Publications: trying again - art_author_id:/Fonag[ ]?.*/
    Author Publications: Number found: 136
    >>> resp = authors_get_author_publications(author_partial="Levinson, Nadine A.")
    Author Publications: Number found: 8
    """
    ret_val = {}
    query = "art_author_id:/{}/".format(author_partial)
    aut_fields = "art_author_id, art_year_int, art_id, art_auth_pos_int, art_author_role, art_author_bio, art_citeas_xml"
    # wildcard in case nothing found for #1
    results = solr_authors.query( q = "{}".format(query),   
                                  fields = aut_fields,
                                  sort="art_author_id, art_year_int", sort_order="asc",
                                  rows=limit, start=offset
                                )

    logger.debug("Author Publications: Number found: %s", results._numFound)
    
    if results._numFound == 0:
        logger.debug("Author Publications: Query didn't work - %s", query)
        query = "art_author_id:/{}[ ]?.*/".format(author_partial)
        logger.debug("Author Publications: trying again - %s", query)
        results = solr_authors.query( q = "{}".format(query),  
                                      fields = aut_fields,
                                      sort="art_author_id, art_year_int", sort_order="asc",
                                      rows=limit, start=offset
                                    )

        logger.debug("Author Publications: Number found: %s", results._numFound)
        if results._numFound == 0:
            query = "art_author_id:/(.*[ ])?{}[ ]?.*/".format(author_partial)
            logger.debug("Author Publications: trying again - %s", query)
            results = solr_authors.query( q = "{}".format(query),  
                                          fields = aut_fields,
                                          sort="art_author_id, art_year_int", sort_order="asc",
                                          rows=limit, start=offset
                                        )
    
    response_info = models.ResponseInfo( count = len(results.results),
                                         fullCount = results._numFound,
                                         limit = limit,
                                         offset = offset,
                                         listType="authorpublist",
                                         scopeQuery=query,
                                         solrParams = results._params,
                                         fullCountComplete = limit >= results._numFound,
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                       )

    author_pub_list_items = []
    for result in results.results:
        citeas = result.get("art_citeas_xml", None)
        citeas = force_string_return_from_various_return_types(citeas)
        
        item = models.AuthorPubListItem( authorID = result.get("art_author_id", None), 
                                         documentID = result.get("art_id", None),
                                         documentRefHTML = citeas,
                                         documentRef = opasxmllib.xml_elem_or_str_to_text(citeas, default_return=""),
                                         documentURL = documentURL + result.get("art_id", None),
                                         year = result.get("art_year", None),
                                         score = result.get("score", 0)
                                        ) 

        author_pub_list_items.append(item)
       
    response_info.count = len(author_pub_list_items)
    
    author_pub_list_struct = models.AuthorPubListStruct( responseInfo = response_info, 
                                           responseSet = author_pub_list_items
                                           )
    
    author_pub_list = models.AuthorPubList(authorPubList = author_pub_list_struct)
    
    ret_val = author_pub_list
    return ret_val

#-----------------------------------------------------------------------------
def get_excerpt_from_abs_sum_or_doc(xml_abstract, xml_summary, xml_document):
   
    ret_val = None
    # see if there's an abstract
    ret_val = force_string_return_from_various_return_types(xml_abstract)
    if ret_val is None:
        # try the summary
        ret_val = force_string_return_from_various_return_types(xml_summary)
        if ret_val is None:
            # get excerpt from the document
            if xml_document is None:
                # we fail.  Return None
                logger.warning("No excerpt can be found or generated.")
            else:
                # extract the first 10 paras
                ret_val = force_string_return_from_various_return_types(xml_document)
                ret_val = opasxmllib.remove_encoding_string(ret_val)
                # deal with potentially broken XML excerpts
                parser = lxml.etree.XMLParser(encoding='utf-8', recover=True)                
                #root = etree.parse(StringIO(ret_val), parser)
                root = etree.fromstring(ret_val, parser)
                body = root.xpath("//*[self::h1 or self::p or self::p2 or self::pb]")
                ret_val = ""
                count = 0
                for elem in body:
                    if elem.tag == "pb" or count > 10:
                        # we're done.
                        ret_val = "%s%s%s" % ("<abs><unit type='excerpt'>", ret_val, "</unit></abs>")
                        break
                    else:
                        ret_val  += etree.tostring(elem, encoding='utf8').decode('utf8')

    return ret_val
    
#-----------------------------------------------------------------------------
def documents_get_abstracts(document_id, ret_format="TEXTONLY", authenticated=None, limit=opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, offset=0):
    """
    Returns an abstract or summary for the specified document
    If part of a documentID is supplied, multiple abstracts will be returned.
    
    The endpoint reminds me that we should be using documentID instead of "art" for article perhaps.
      Not thrilled about the prospect of changing it, but probably the right thing to do.
      
    >>> abstracts = documents_get_abstracts("IJP.075")
    10 document matches for getAbstracts
    >>> abstracts = documents_get_abstracts("AIM.038.0279A")  # no abstract on this one
    1 document matches for getAbstracts
    >>> abstracts = documents_get_abstracts("AIM.040.0311A")
    1 document matches for getAbstracts
      
    """
    ret_val = None
    results = solr_docs.query(q = "art_id:%s*" % (document_id),  
                                fields = "art_id, art_pepsourcetitlefull, art_vol, art_year, art_citeas_xml, art_pgrg, art_title_xml, art_authors, abstracts_xml, summaries_xml, text_xml",
                                sort="art_year, art_pgrg", sort_order="asc",
                                rows=limit, start=offset
                             )
    
    matches = len(results.results)
    cwd = os.getcwd()    
    # print ("GetAbstract: Current Directory {}".format(cwd))
    logger.debug ("%s document matches for getAbstracts", matches)
    
    response_info = models.ResponseInfo( count = len(results.results),
                                         fullCount = results._numFound,
                                         limit = limit,
                                         offset = offset,
                                         listType="documentlist",
                                         fullCountComplete = limit >= results._numFound,
                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                       )
    
    document_item_list = []
    for result in results:
        if matches > 0:
            try:
                xml_abstract = result["abstracts_xml"]
            except KeyError as e:
                xml_abstract = None
                logger.info("No abstract for document ID: %s", document_id)
        
            try:
                xml_summary = result["summaries_xml"]
            except KeyError as e:
                xml_summary = None
                logger.info("No summary for document ID: %s", document_id)
        
            try:
                xml_document = result["text_xml"]
            except KeyError as e:
                xml_document = None
                logger.error("No content matched document ID for: %s", document_id)

            author_ids = result.get("art_authors", None)
            if author_ids is None:
                author_mast = None
            else:
                author_mast = opasgenlib.deriveAuthorMast(author_ids)

            pgrg = result.get("art_pgrg", None)
            pg_start, pg_end = opasgenlib.pgrg_splitter(pgrg)
            
            source_title = result.get("art_pepsourcetitlefull", None)
            title = result.get("art_title_xml", "")  # name is misleading, it's not xml.
            art_year = result.get("art_year", None)
            art_vol = result.get("art_vol", None)

            citeas = result.get("art_citeas_xml", None)
            citeas = force_string_return_from_various_return_types(citeas)

            abstract = get_excerpt_from_abs_sum_or_doc(xml_abstract, xml_summary, xml_document)
            if abstract == "[]":
                abstract = None
            elif ret_format == "TEXTONLY":
                abstract = opasxmllib.xml_elem_or_str_to_text(abstract)
            elif ret_format == "HTML":
                abstractHTML = opasxmllib.xml_str_to_html(abstract)
                abstract = extract_html_fragment(abstractHTML, "//div[@id='abs']")

            abstract = opasxmllib.add_headings_to_abstract_html(abstract=abstract, 
                                                            source_title=source_title,
                                                            pub_year=art_year,
                                                            vol=art_vol, 
                                                            pgrg=pgrg, 
                                                            citeas=citeas, 
                                                            title=title,
                                                            author_mast=author_mast )

            item = models.DocumentListItem(year = art_year,
                                    vol = art_vol,
                                    sourceTitle = source_title,
                                    pgRg = pgrg,
                                    pgStart = pg_start,
                                    pgEnd = pg_end,
                                    authorMast = author_mast,
                                    documentID = result.get("art_id", None),
                                    documentRefHTML = citeas,
                                    documentRef = opasxmllib.xml_elem_or_str_to_text(citeas, default_return=""),
                                    accessLimited = authenticated,
                                    abstract = abstract,
                                    score = result.get("score", None)
                                    )
        
            document_item_list.append(item)

    response_info.count = len(document_item_list)
    
    document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                      responseSet=document_item_list
                                                      )
    
    documents = models.Documents(documents = document_list_struct)
        
    ret_val = documents
            
                
    return ret_val


#-----------------------------------------------------------------------------
def documents_get_document(document_id, solr_query_params=None, ret_format="XML", authenticated=True, limit=opasConfig.DEFAULT_LIMIT_FOR_DOCUMENT_RETURNS, offset=0):
    """
   For non-authenticated users, this endpoint returns only Document summary information (summary/abstract)
   For authenticated users, it returns with the document itself
   
    >> resp = documents_get_document("AIM.038.0279A", ret_format="html") 
    
    >> resp = documents_get_document("AIM.038.0279A") 
    
    >> resp = documents_get_document("AIM.040.0311A")
    

    """
    ret_val = {}
    
    if not authenticated:
        #if user is not authenticated, effectively do endpoint for getDocumentAbstracts
        logger.info("documentsGetDocument: User not authenticated...fetching abstracts instead")
        ret_val = document_list_struct = documents_get_abstracts(document_id, authenticated=authenticated, limit=1)
        return ret_val

    if solr_query_params is not None:
        # repeat the query that the user had done when retrieving the document
        query = "art_id:{} && {}".format(document_id, solr_query_params.searchQ)
        document_list = search_text(query, 
                                    filter_query = solr_query_params.filterQ,
                                    full_text_requested=True,
                                    full_text_format_requested = ret_format,
                                    authenticated=authenticated,
                                    query_debug = False,
                                    dis_max = solr_query_params.solrMax,
                                    limit=limit, 
                                    offset=offset
                                  )
    
    if document_list == None or document_list.documentList.responseInfo.count == 0:
        #sometimes the query is still sent back, even though the document was an independent selection.  So treat it as a simple doc fetch
        
        query = "art_id:{}".format(document_id)
        #summaryFields = "art_id, art_vol, art_year, art_citeas_xml, art_pgrg, art_title, art_author_id, abstracts_xml, summaries_xml, text_xml"
       
        document_list = search_text(query, 
                                    full_text_requested=True,
                                    full_text_format_requested = ret_format,
                                    authenticated=authenticated,
                                    query_debug = False,
                                    limit=limit, 
                                    offset=offset
                                    )

    try:
        matches = document_list.documentList.responseInfo.count
        full_count = document_list.documentList.responseInfo.fullCount
        full_count_complete = document_list.documentList.responseInfo.fullCountComplete
        document_list_item = document_list.documentList.responseSet[0]
        logger.debug("documentsGetDocument %s document matches", matches)
    except Exception as e:
        logger.info("No matches or error: %s", e)
    else:
        response_info = models.ResponseInfo( count = matches,
                                             fullCount = full_count,
                                             limit = limit,
                                             offset = offset,
                                             listType="documentlist",
                                             fullCountComplete = full_count_complete,
                                             timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)
                                           )
        
        if matches >= 1:       
            document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                              responseSet = [document_list_item]
                                                            )
                
            documents = models.Documents(documents = document_list_struct)
                    
            ret_val = documents
    
    return ret_val

#-----------------------------------------------------------------------------
def documents_get_glossary_entry(term_id,
                                 solrQueryParams=None,
                                 retFormat="XML",
                                 authenticated=True,
                                 limit=opasConfig.DEFAULT_LIMIT_FOR_DOCUMENT_RETURNS, offset=0):
    """
    For non-authenticated users, this endpoint should return an error (#TODO)
    
    For authenticated users, it returns with the glossary itself
   
    IMPORTANT NOTE: At least the way the database is currently populated, for a group, the textual part (text) is the complete group, 
      and thus the same for all entries.  This is best for PEP-Easy now, otherwise, it would need to concatenate all the result entries.
   
    >> resp = documentsGetGlossaryEntry("ZBK.069.0001o.YN0019667860580", retFormat="html") 
    
    >> resp = documentsGetGlossaryEntry("ZBK.069.0001o.YN0004676559070") 
    
    >> resp = documentsGetGlossaryEntry("ZBK.069.0001e.YN0005656557260")
    

    """
    ret_val = {}
    term_id = term_id.upper()
    
    if not authenticated:
        #if user is not authenticated, effectively do endpoint for getDocumentAbstracts
        documents_get_abstracts(term_id, limit=1)
    else:
        results = solr_gloss.query(q = f"term_id:{term_id} || group_id:{term_id}",  
                                  fields = "term_id, group_id, term_type, term_source, group_term_count, art_id, text"
                                 )
        document_item_list = []
        count = 0
        try:
            for result in results:
                try:
                    document = result.get("text", None)
                    if retFormat == "HTML":
                        document = opasxmllib.xml_str_to_html(document)
                    else:
                        document = document
                    item = models.DocumentListItem(PEPCode = "ZBK", 
                                                   documentID = result.get("art_id", None), 
                                                   title = result.get("term_source", None),
                                                   abstract = None,
                                                   document = document,
                                                   score = result.get("score", None)
                                            )
                except ValidationError as e:
                    logger.error(e.json())  
                else:
                    document_item_list.append(item)
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
                                                 listType="documentlist",
                                                 fullCountComplete = True,
                                                 timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                               )
            
            document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                              responseSet = document_item_list
                                                            )
                
            documents = models.Documents(documents = document_list_struct)
                        
            ret_val = documents
        
        return ret_val

#-----------------------------------------------------------------------------
def prep_document_download(document_id, ret_format="HTML", authenticated=True, base_filename="opasDoc"):
    """
   For non-authenticated users, this endpoint returns only Document summary information (summary/abstract)
   For authenticated users, it returns with the document itself
   
    >>> a = prep_document_download("IJP.051.0175A", ret_format="html") 
    
    >> a = prep_document_download("IJP.051.0175A", ret_format="epub") 
    

    """
    def add_epub_elements(str):
        # for now, just return
        return str
        
    ret_val = None
    
    if authenticated:
        results = solr_docs.query( q = "art_id:%s" % (document_id),  
                                   fields = "art_id, art_citeas_xml, text_xml"
                                 )
        try:
            ret_val = results.results[0]["text_xml"]
        except IndexError as e:
            logger.warning("No matching document for %s.  Error: %s", document_id, e)
        except KeyError as e:
            logger.warning("No content or abstract found for %s.  Error: %s", document_id, e)
        else:
            try:    
                if isinstance(ret_val, list):
                    ret_val = ret_val[0]
            except Exception as e:
                logger.warning("Empty return: %s", e)
            else:
                try:    
                    if ret_format.upper() == "HTML":
                        ret_val = opasxmllib.remove_encoding_string(ret_val)
                        filename = convert_xml_to_html_file(ret_val, output_filename=document_id + ".html")  # returns filename
                        ret_val = filename
                    elif ret_format.upper() == "PDFORIG":
                        ret_val = find(document_id + ".PDF", opasConfig.PDFORIGDIR)
                    elif ret_format.upper() == "PDF":
                        ret_val = opasxmllib.remove_encoding_string(ret_val)
                        html_string = opasxmllib.xml_str_to_html(ret_val)
                        # open output file for writing (truncated binary)
                        filename = document_id + ".PDF" 
                        result_file = open(filename, "w+b")
                        # convert HTML to PDF
                        pisaStatus = pisa.CreatePDF(html_string,                # the HTML to convert
                                                    dest=result_file)           # file handle to recieve result
                        # close output file
                        result_file.close()                 # close output file
                        # return True on success and False on errors
                        ret_val = filename
                    elif ret_format.upper() == "EPUB":
                        ret_val = opasxmllib.remove_encoding_string(ret_val)
                        html_string = opasxmllib.xml_str_to_html(ret_val)
                        html_string = add_epub_elements(html_string)
                        filename = opasxmllib.html_to_epub(html_string, document_id, document_id)
                        ret_val = filename
                    else:
                        logger.warning(f"Format {ret_format} not supported")
                        
                except Exception as e:
                    logger.warning("Can't convert data: %s", e)
        
    return ret_val

#-----------------------------------------------------------------------------
def find(name, path):
    """
    Find the file name in the selected path
    """
    for root, dirs, files in os.walk(path):
        if name.lower() in [x.lower() for x in files]:
            return os.path.join(root, name)

#-----------------------------------------------------------------------------
def convert_xml_to_html_file(xmltext_str, xslt_file=r"./styles/pepkbd3-html.xslt", output_filename=None):
    if output_filename is None:
        basename = "opasDoc"
        suffix = datetime.datetime.now().strftime("%y%m%d_%H%M%S")
        filename_base = "_".join([basename, suffix]) # e.g. 'mylogfile_120508_171442'        
        output_filename = filename_base + ".html"

    htmlString = opasxmllib.xml_str_to_html(xmltext_str, xslt_file=xslt_file)
    fo = open(output_filename, "w", encoding="utf-8")
    fo.write(str(htmlString))
    fo.close()
    
    return output_filename

#-----------------------------------------------------------------------------
def get_image_binary(image_id):
    """
    Return a binary object of the image, e.g.,
   
    >>> get_image_binary("NOTEXISTS.032.0329A.F0003g")

    >> get_image_binary("AIM.036.0275A.FIG001")

    >> get_image_binary("JCPTX.032.0329A.F0003g")
    
    Note: the current server requires the extension, but it should not.  The server should check
    for the file per the following extension hierarchy: .jpg then .gif then .tif
    
    However, if the extension is supplied, that should be accepted.

    The current API implements this:
    
    curl -X GET "http://stage.pep.gvpi.net/api/v1/Documents/Downloads/Images/aim.036.0275a.fig001.jpg" -H "accept: image/jpeg" -H "Authorization: Basic cC5lLnAuYS5OZWlsUlNoYXBpcm86amFDayFsZWdhcmQhNQ=="
    
    and returns a binary object.
    
        
    """
    def getImageFilename(image_id):
        image_source_path = "X:\_PEPA1\g"
        ext = os.path.splitext(image_source_path)[-1].lower()
        if ext in (".jpg", ".tif", ".gif"):
            image_filename = os.path.join(image_source_path, image_id)
            exists = os.path.isfile(image_filename)
            if not exists:
                image_filename = None
        else:
            image_filename = os.path.join(image_source_path, image_id + ".jpg")
            exists = os.path.isfile(image_filename)
            if not exists:
                image_filename = os.path.join(image_source_path, image_id + ".gif")
                exists = os.path.isfile(image_filename)
                if not exists:
                    image_filename = os.path.join(image_source_path, image_id + ".tif")
                    exists = os.path.isfile(image_filename)
                    if not exists:
                        image_filename = None

        return image_filename
    
    # these won't be in the Solr database, needs to be brought back by a file
    # the file ID should match a file name
    ret_val = None
    image_filename = getImageFilename(image_id)
    if image_filename is not None:
        try:
            f = open(image_filename, "rb")
            image_bytes = f.read()
            f.close()    
        except OSError as e:
            logger.error("getImageBinary: File Open Error: %s", e)
        except Exception as e:
            logger.error("getImageBinary: Error: %s", e)
        else:
            ret_val = image_bytes
    else:
        logger.error("Image File ID %s not found", image_id)
  
    return ret_val

#-----------------------------------------------------------------------------
def get_kwic_list(marked_up_text, 
                  extra_context_len=opasConfig.DEFAULT_KWIC_CONTENT_LENGTH, 
                  solr_start_hit_tag=opasConfig.HITMARKERSTART, # supply whatever the start marker that solr was told to use
                  solr_end_hit_tag=opasConfig.HITMARKEREND,     # supply whatever the end marker that solr was told to use
                  output_start_hit_tag_marker=opasConfig.HITMARKERSTART_OUTPUTHTML, # the default output marker, in HTML
                  output_end_hit_tag_marker=opasConfig.HITMARKEREND_OUTPUTHTML,
                  limit=opasConfig.DEFAULT_MAX_KWIC_RETURNS):
    """
    Find all nonoverlapping matches, using Solr's return.  Limit the number.
    
    (See git version history for an earlier -- and different version)
    """
    
    ret_val = []
    em_marks = re.compile("(.{0,%s}%s.*%s.{0,%s})" % (extra_context_len, solr_start_hit_tag, solr_end_hit_tag, extra_context_len))
    marked_up = re.compile(".*(%s.*%s).*" % (solr_start_hit_tag, solr_end_hit_tag))
    marked_up_text = opasxmllib.xml_string_to_text(marked_up_text) # remove markup except match tags which shouldn't be XML

    match_text_pattern = "({{.*?}})"
    pat_compiled = re.compile(match_text_pattern)
    word_list = pat_compiled.split(marked_up_text) # split all the words
    index = 0
    count = 0
    #TODO may have problems with adjacent matches!
    skip_next = False
    for n in word_list:
        if pat_compiled.match(n) and skip_next == False:
            # we have a match
            try:
                text_before = word_list[index-1]
                text_before_words = text_before.split(" ")[-extra_context_len:]
                text_before_phrase = " ".join(text_before_words)
            except:
                text_before = ""
            try:
                text_after = word_list[index+1]
                text_after_words = text_after.split(" ")[:extra_context_len]
                text_after_phrase = " ".join(text_after_words)
                if pat_compiled.search(text_after_phrase):
                    skip_next = True
            except:
                text_after = ""

            # change the tags the user told Solr to use to the final output tags they want
            #   this is done to use non-xml-html hit tags, then convert to that after stripping the other xml-html tags
            match = re.sub(solr_start_hit_tag, output_start_hit_tag_marker, n)
            match = re.sub(solr_end_hit_tag, output_end_hit_tag_marker, match)

            context_phrase = text_before_phrase + match + text_after_phrase

            ret_val.append(context_phrase)

            try:
                logger.info("getKwicList Match: '...{}...'".format(context_phrase))
            except Exception as e:
                logger.error("getKwicList Error printing or logging matches. %s", e)
            
            index += 1
            count += 1
            if count >= limit:
                break
        else:
            skip_next = False
            index += 1
        
    # matchCount = len(ret_val)
    
    return ret_val    


##-----------------------------------------------------------------------------
#def get_kwic_list_old(marked_up_text, extra_context_len=opasConfig.DEFAULT_KWIC_CONTENT_LENGTH, 
                #solr_start_hit_tag=opasConfig.HITMARKERSTART, # supply whatever the start marker that solr was told to use
                #solr_end_hit_tag=opasConfig.HITMARKEREND,     # supply whatever the end marker that solr was told to use
                #output_start_hit_tag_marker=opasConfig.HITMARKERSTART_OUTPUTHTML, # the default output marker, in HTML
                #output_end_hit_tag_marker=opasConfig.HITMARKEREND_OUTPUTHTML,
                #limit=opasConfig.DEFAULT_MAX_KWIC_RETURNS):
    #"""
    #Find all nonoverlapping matches, using Solr's return.  Limit the number.
    #"""
    
    #ret_val = []
    #em_marks = re.compile("(.{0,%s}%s.*%s.{0,%s})" % (extra_context_len, solr_start_hit_tag, solr_end_hit_tag, extra_context_len))
    #count = 0
    #for n in em_marks.finditer(marked_up_text):
        #count += 1
        #match = n.group(0)
        #try:
            ## strip xml
            #match = opasxmllib.xml_string_to_text(match)
            ## change the tags the user told Solr to use to the final output tags they want
            ##   this is done to use non-xml-html hit tags, then convert to that after stripping the other xml-html tags
            #match = re.sub(solr_start_hit_tag, output_start_hit_tag_marker, match)
            #match = re.sub(solr_end_hit_tag, output_end_hit_tag_marker, match)
        #except Exception as e:
            #logging.error("Error stripping xml from kwic entry {}".format(e))
               
        #ret_val.append(match)
        #try:
            #logger.info("getKwicList Match: '...{}...'".format(match))
            #print ("getKwicListMatch: '...{}...'".format(match))
        #except Exception as e:
            #print ("getKwicList Error printing or logging matches. {}".format(e))
        #if count >= limit:
            #break
        
    #match_count = len(ret_val)
    
    #return ret_val    

#-----------------------------------------------------------------------------
def year_arg_parser(year_arg):
    ret_val = None
    year_query = re.match("[ ]*(?P<option>[\>\^\<\=])?[ ]*(?P<start>[12][0-9]{3,3})?[ ]*(?P<separator>([-]|TO))*[ ]*(?P<end>[12][0-9]{3,3})?[ ]*", year_arg, re.IGNORECASE)            
    if year_query is None:
        logger.warning("Search - StartYear bad argument {}".format(year_arg))
    else:
        option = year_query.group("option")
        start = year_query.group("start")
        end = year_query.group("end")
        separator = year_query.group("separator")
        if start is None and end is None:
            logger.warning("Search - StartYear bad argument {}".format(year_arg))
        else:
            if option == "^":
                # between
                # find endyear by parsing
                if start is None:
                    start = end # they put > in start rather than end.
                elif end is None:
                    end = start # they put < in start rather than end.
                search_clause = "&& art_year_int:[{} TO {}] ".format(start, end)
            elif option == ">":
                # greater
                if start is None:
                    start = end # they put > in start rather than end.
                search_clause = "&& art_year_int:[{} TO {}] ".format(start, "*")
            elif option == "<":
                # less than
                if end is None:
                    end = start # they put < in start rather than end.
                search_clause = "&& art_year_int:[{} TO {}] ".format("*", end)
            else: # on
                if start is not None and end is not None:
                    # they specified a range anyway
                    search_clause = "&& art_year_int:[{} TO {}] ".format(start, end)
                elif start is None and end is not None:
                    # they specified '- endyear' without the start, so less than
                    search_clause = "&& art_year_int:[{} TO {}] ".format("*", end)
                elif start is not None and separator is not None:
                    # they mean greater than
                    search_clause = "&& art_year_int:[{} TO {}] ".format(start, "*")
                else: # they mean on
                    search_clause = "&& art_year_int:{} ".format(year_arg)

            ret_val = search_clause

    return ret_val
                        
#-----------------------------------------------------------------------------
def search_analysis(query_list, 
                    filter_query = None,
                    more_like_these = False,
                    query_analysis = False,
                    dis_max = None,
                    # summaryFields="art_id, art_pepsrccode, art_vol, art_year, art_iss, 
                        # art_iss_title, art_newsecnm, art_pgrg, art_title, art_author_id, art_citeas_xml", 
                    summary_fields="art_id",                    
                    # highlightFields='art_title_xml, abstracts_xml, summaries_xml, art_authors_xml, text_xml', 
                    full_text_requested=False, 
                    user_logged_in=False,
                    limit=opasConfig.DEFAULT_MAX_KWIC_RETURNS
                   ):
    """
    Analyze the search clauses in the query list
	"""
    ret_val = {}
    document_item_list = []
    rowCount = 0
    for n in query_list:
        n = n[3:]
        n = n.strip(" ")
        if n == "" or n is None:
            continue

        results = solr_docs.query(n,
                                 disMax = dis_max,
                                 queryAnalysis = True,
                                 fields = summary_fields,
                                 rows = 1,
                                 start = 0)
    
        termField, termValue = n.split(":")
        if termField == "art_author_xml":
            term = termValue + " ( in author)"
        elif termField == "text_xml":
            term = termValue + " ( in text)"
            
        logger.debug("Analysis: Term %s, matches %s", n, results._numFound)
        item = models.DocumentListItem(term = n, 
                                termCount = results._numFound
                                )
        document_item_list.append(item)
        rowCount += 1

    if rowCount > 0:
        numFound = 0
        item = models.DocumentListItem(term = "combined",
                                termCount = numFound
                                )
        document_item_list.append(item)
        rowCount += 1
        print ("Analysis: Term %s, matches %s" % ("combined: ", numFound))

    response_info = models.ResponseInfo(count = rowCount,
                                        fullCount = rowCount,
                                        listType = "srclist",
                                        fullCountComplete = True,
                                        timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)
                                        )
    
    response_info.count = len(document_item_list)
    
    document_list_struct = models.DocumentListStruct( responseInfo = response_info, 
                                                      responseSet = document_item_list
                                                  )
    
    ret_val = models.DocumentList(documentList = document_list_struct)
    
    return ret_val

#================================================================================================================
# SEARCHTEXT
#================================================================================================================
def search_text(query, 
               filter_query = None,
               query_debug = False,
               more_like_these = False,
               full_text_requested = False, 
               full_text_format_requested = "HTML",
               dis_max = None,
               # bring text_xml back in summary fields in case it's missing in highlights! I documented a case where this happens!
               # summary_fields = "art_id, art_pepsrccode, art_vol, art_year, art_iss, art_iss_title, art_newsecnm, art_pgrg, art_title, art_author_id, art_citeas_xml, text_xml", 
               # highlight_fields = 'art_title_xml, abstracts_xml, summaries_xml, art_authors_xml, text_xml', 
               summary_fields = "art_id, art_pepsrccode, art_vol, art_year, art_iss, art_iss_title, art_newsecnm, art_pgrg, abstracts_xml, art_title, art_author_id, art_citeas_xml, text_xml", 
               highlight_fields = 'text_xml', 
               sort_by="score desc",
               authenticated = None, 
               extra_context_len = opasConfig.DEFAULT_KWIC_CONTENT_LENGTH,
               maxKWICReturns = opasConfig.DEFAULT_MAX_KWIC_RETURNS,
               limit=opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, 
               offset=0):
    """
    Full-text search

    >>> ret = search_text(query="art_title_xml:'ego identity'", limit=10, offset=0, full_text_requested=False)
    Search Performed: art_title_xml:'ego identity'
    Result  Set Size: 12809
    Return set limit: 10
    
        Original Parameters in API
        Original API return model example, needs to be supported:
    
                "authormast": "Ringstrom, P.A.",
				"documentID": "IJPSP.005.0257A",
				"documentRef": "Ringstrom, P.A. (2010). Commentary on Donna Orange's, &#8220;Recognition as: Intersubjective Vulnerability in the Psychoanalytic Dialogue&#8221;. Int. J. Psychoanal. Self Psychol., 5(3):257-273.",
				"issue": "3",
				"PEPCode": "IJPSP",
				"pgStart": "257",
				"pgEnd": "273",
				"title": "Commentary on Donna Orange's, &#8220;Recognition as: Intersubjective Vulnerability in the Psychoanalytic Dialogue&#8221;",
				"vol": "5",
				"year": "2010",
				"rank": "100",
				"citeCount5": "1",
				"citeCount10": "3",
				"citeCount20": "3",
				"citeCountAll": "3",
				"kwic": ". . . \r\n        

    
    """
    ret_val = {}
    ret_status = (200, "OK") # default is like HTTP_200_OK
    
    if more_like_these:
        mlt_fl = "text_xml, headings_xml, terms_xml, references_xml"
        mlt = "true"
        mlt_minwl = 8
    else:
        mlt_fl = None
        mlt = "false"
        mlt_minwl = None
    
    if query_debug:
        query_debug = "on"
    else:
        query_debug = "off"
        
    if full_text_requested:
        fragSize = opasConfig.SOLR_HIGHLIGHT_RETURN_FRAGMENT_SIZE 
    else:
        fragSize = extra_context_len

    if filter_query == "*:*":
        # drop it...it seems to produce problems in simple queries that follow a search.
        filter_query = None
    elif filter_query is not None:
        # for logging/debug
        logger.debug("Solr FilterQ: %s", filter_query)

    if query is not None:
        logger.debug("Solr Query: %s", query)

    try:
        results = solr_docs.query(query,  
                                 fq = filter_query,
                                 debugQuery = query_debug,
                                 disMax = dis_max,
                                 fields = summary_fields,
                                 hl='true', 
                                 hl_fragsize = fragSize, 
                                 hl_multiterm = 'true',
                                 hl_fl = highlight_fields,
                                 hl_usePhraseHighlighter = 'true',
                                 hl_snippets = maxKWICReturns,
                                 #hl_method="unified",  # these don't work
                                 #hl_encoder="HTML",
                                 mlt = mlt,
                                 mlt_fl = mlt_fl,
                                 mlt_count = 2,
                                 mlt_minwl = mlt_minwl,
                                 rows = limit,
                                 start = offset,
                                 sort=sort_by,
                                 hl_simple_pre = opasConfig.HITMARKERSTART,
                                 hl_simple_post = opasConfig.HITMARKEREND)
    except solr.SolrException as e:
        logger.error(f"Solr Runtime Search Error: {e}")
        ret_status = (400, e) # e has type <class 'solrpy.core.SolrException'>, with useful elements of httpcode, reason, and body, e.g.,
                              #  (I added the 400 first element, because then I have a known quantity to catch)
                              #  httpcode: 400
                              #  reason: 'Bad Request'
                              #  body: b'<?xml version="1.0" encoding="UTF-8"?>\n<response>\n\n<lst name="responseHeader">\n  <int name="status">400</int>\n  <int name="QTime">0</int>\n  <lst name="params">\n    <str name="hl">true</str>\n    <str name="fl">art_id, art_pepsrccode, art_vol, art_year, art_iss, art_iss_title, art_newsecnm, art_pgrg, abstracts_xml, art_title, art_author_id, art_citeas_xml, text_xml,score</str>\n    <str name="hl.fragsize">200</str>\n    <str name="hl.usePhraseHighlighter">true</str>\n    <str name="start">0</str>\n    <str name="fq">*:* </str>\n    <str name="mlt.minwl">None</str>\n    <str name="sort">rank asc</str>\n    <str name="rows">15</str>\n    <str name="hl.multiterm">true</str>\n    <str name="mlt.count">2</str>\n    <str name="version">2.2</str>\n    <str name="hl.simple.pre">%##</str>\n    <str name="hl.snippets">5</str>\n    <str name="q">*:* &amp;&amp; text:depression &amp;&amp; text:"passive withdrawal" </str>\n    <str name="mlt">false</str>\n    <str name="hl.simple.post">##%</str>\n    <str name="disMax">None</str>\n    <str name="mlt.fl">None</str>\n    <str name="hl.fl">text_xml</str>\n    <str name="wt">xml</str>\n    <str name="debugQuery">off</str>\n  </lst>\n</lst>\n<lst name="error">\n  <lst name="metadata">\n    <str name="error-class">org.apache.solr.common.SolrException</str>\n    <str name="root-error-class">org.apache.solr.common.SolrException</str>\n  </lst>\n  <str name="msg">sort param field can\'t be found: rank</str>\n  <int name="code">400</int>\n</lst>\n</response>\n'

    else: #  search was ok
        logger.debug("Search Performed: %s", query)
        logger.debug("The Filtering: %s", query)
        logger.debug("Result  Set Size: %s", results._numFound)
        logger.debug("Return set limit: %s", limit)
        if results._numFound == 0:
            try:
                # try removing the filter query
                results = solr_docs.query(query,  
                                         debugQuery = query_debug,
                                         disMax = dis_max,
                                         fields = summary_fields,
                                         hl='true', 
                                         hl_fragsize = fragSize, 
                                         hl_multiterm='true',
                                         hl_fl = highlight_fields,
                                         hl_usePhraseHighlighter = 'true',
                                         hl_snippets = maxKWICReturns,
                                         #hl_method="unified",  # these don't work
                                         #hl_encoder="HTML",
                                         mlt = mlt,
                                         mlt_fl = mlt_fl,
                                         mlt_count = 2,
                                         mlt_minwl = mlt_minwl,
                                         rows = limit,
                                         start = offset,
                                         sort=sort_by,
                                         hl_simple_pre = opasConfig.HITMARKERSTART,
                                         hl_simple_post = opasConfig.HITMARKEREND)
            except solr.SolrException as e:
                logger.error(f"Solr Runtime Search Error: {e}")
                # e has type <class 'solrpy.core.SolrException'>, with useful elements of httpcode, reason, and body, e.g.,
                ret_status = (400, e) 
            else:
                logger.debug("Re-formed Search: %s", query)
                logger.debug("New Result Set Size: %s", results._numFound)
                logger.debug("Return set limit: %s", limit)

        if ret_status[0] == 200: 
            # Solr search was ok
            responseInfo = models.ResponseInfo(
                             count = len(results.results),
                             fullCount = results._numFound,
                             totalMatchCount = results._numFound,
                             limit = limit,
                             offset = offset,
                             listType="documentlist",
                             scopeQuery=query,
                             fullCountComplete = limit >= results._numFound,
                             solrParams = results._params,
                             timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                           )
       
            documentItemList = []
            rowCount = 0
            rowOffset = 0
            # if we're not authenticated, then turn off the full-text request and behave as if we didn't try
            if not authenticated:
                if full_text_requested:
                    logger.warning("Fulltext requested--by API--but not authenticated.")
        
                full_text_requested = False
                
            for result in results.results:
                authorIDs = result.get("art_author_id", None)
                if authorIDs is None:
                    authorMast = None
                else:
                    authorMast = opasgenlib.deriveAuthorMast(authorIDs)
        
                pgRg = result.get("art_pgrg", None)
                if pgRg is not None:
                    pgStart, pgEnd = opasgenlib.pgrg_splitter(pgRg)
                    
                documentID = result.get("art_id", None)        
                text_xml = results.highlighting[documentID].get("text_xml", None)
                # no kwic list when full-text is requested.
                if text_xml is not None and not full_text_requested:
                    #kwicList = getKwicList(textXml, extraContextLen=extraContextLen)  # returning context matches as a list, making it easier for clients to work with
                    kwic_list = []
                    for n in text_xml:
                        # strip all tags
                        match = opasxmllib.xml_string_to_text(n)
                        # change the tags the user told Solr to use to the final output tags they want
                        #   this is done to use non-xml-html hit tags, then convert to that after stripping the other xml-html tags
                        match = re.sub(opasConfig.HITMARKERSTART, opasConfig.HITMARKERSTART_OUTPUTHTML, match)
                        match = re.sub(opasConfig.HITMARKEREND, opasConfig.HITMARKEREND_OUTPUTHTML, match)
                        kwic_list.append(match)
                        
                    kwic = " . . . ".join(kwic_list)  # how its done at GVPi, for compatibility (as used by PEPEasy)
                    text_xml = None
                    #print ("Document Length: {}; Matches to show: {}".format(len(textXml), len(kwicList)))
                else: # either fulltext requested, or no document
                    kwic_list = []
                    kwic = ""  # this has to be "" for PEP-Easy, or it hits an object error.  
                
                if full_text_requested:
                    fullText = result.get("text_xml", None)
                    text_xml = force_string_return_from_various_return_types(text_xml)
                    if text_xml is None:  # no highlights, so get it from the main area
                        try:
                            text_xml = fullText
                        except:
                            text_xml = None
     
                    elif len(fullText) > len(text_xml):
                        logger.warning("Warning: text with highlighting is smaller than full-text area.  Returning without hit highlighting.")
                        text_xml = fullText
                        
                    if full_text_format_requested == "HTML":
                        if text_xml is not None:
                            text_xml = opasxmllib.xml_str_to_html(text_xml,
                                                                     xslt_file=r"./libs/styles/pepkbd3-html.xslt")
        
                if full_text_requested and not authenticated: # don't do this when textXml is a fragment from kwiclist!
                    try:
                        abstracts_xml = results.highlighting[documentID].get("abstracts_xml", None)
                        abstracts_xml  = force_string_return_from_various_return_types(abstracts_xml )
     
                        summaries_xml = results.highlighting[documentID].get("abstracts_xml", None)
                        summaries_xml  = force_string_return_from_various_return_types(summaries_xml)
     
                        text_xml = get_excerpt_from_abs_sum_or_doc(xml_abstract=abstracts_xml,
                                                                   xml_summary=summaries_xml,
                                                                   xml_document=text_xml)
                    except:
                        text_xml = None
        
                citeAs = result.get("art_citeas_xml", None)
                citeAs = force_string_return_from_various_return_types(citeAs)
                
                if more_like_these:
                    similarDocs = results.moreLikeThis[documentID]
                    similarMaxScore = results.moreLikeThis[documentID].maxScore
                    similarNumFound = results.moreLikeThis[documentID].numFound
                else:
                    similarDocs = None
                    similarMaxScore = None
                    similarNumFound = None
                
                try:
                    item = models.DocumentListItem(PEPCode = result.get("art_pepsrccode", None), 
                                            year = result.get("art_year", None),
                                            vol = result.get("art_vol", None),
                                            pgRg = pgRg,
                                            pgStart = pgStart,
                                            pgEnd = pgEnd,
                                            authorMast = authorMast,
                                            documentID = documentID,
                                            documentRefHTML = citeAs,
                                            documentRef = opasxmllib.xml_elem_or_str_to_text(citeAs, default_return=""),
                                            kwic = kwic,
                                            kwicList = kwic_list,
                                            title = result.get("art_title", None),
                                            abstract = force_string_return_from_various_return_types(result.get("abstracts_xml", None)), # these were highlight versions, not needed
                                            document = text_xml,
                                            score = result.get("score", None), 
                                            rank = rowCount + 1,
                                            similarDocs = similarDocs,
                                            similarMaxScore = similarMaxScore,
                                            similarNumFound = similarNumFound
                                            )
                except ValidationError as e:
                    logger.error(e.json())  
                else:
                    rowCount += 1
                    # logger.info("{}:{}".format(rowCount, citeAs.decode("utf8")))
                    documentItemList.append(item)
                    if rowCount > limit:
                        break
        
        responseInfo.count = len(documentItemList)
        
        documentListStruct = models.DocumentListStruct( responseInfo = responseInfo, 
                                                        responseSet = documentItemList
                                                      )
        
        documentList = models.DocumentList(documentList = documentListStruct)
 
        ret_val = documentList
    
    return ret_val, ret_status

#-----------------------------------------------------------------------------
#def set_cookie(response: Response, name: str, value: Union[str, bytes], *, domain: Optional[str] = None,
               #path: str = '/', expires: Optional[Union[float, Tuple, datetime]] = None,
               #expires_days: Optional[int] = None, max_age: Optional[int] = None, secure=False, httponly=True,
               #samesite: Optional[str] = 'Lax') -> None:
    #"""Sets an outgoing cookie name/value with the given options.

    #Newly-set cookies are not immediately visible via `get_cookie`;
    #they are not present until the next request.

    #expires may be a numeric timestamp as returned by `time.time`,
    #a time tuple as returned by `time.gmtime`, or a
    #`datetime.datetime` object.
    #"""
    #if not name.isidentifier():
        ## Don't let us accidentally inject bad stuff
        #raise ValueError(f'Invalid cookie name: {repr(name)}')
    #if value is None:
        #raise ValueError(f'Invalid cookie value: {repr(value)}')
    ##value = unicode(value)
    #cookie = http.cookies.SimpleCookie()
    #cookie[name] = value
    #morsel = cookie[name]
    #if domain:
        #morsel['domain'] = domain
    #if path:
        #morsel['path'] = path
    #if expires_days is not None and not expires:
        #expires = datetime.utcnow() + timedelta(days=expires_days)
    #if expires:
        #morsel['expires'] = expires
    #if max_age is not None:
        #morsel['max-age'] = max_age
    #parts = [cookie.output(header='').strip()]
    #if secure:
        #parts.append('Secure')
    #if httponly:
        #parts.append('HttpOnly')
    #if samesite:
        #parts.append(f'SameSite={http.cookies._quote(samesite)}')
    #cookie_val = '; '.join(parts)
    #response.raw_headers.append((b'set-cookie', cookie_val.encode('latin-1')))

##-----------------------------------------------------------------------------
#def delete_cookie(response: Response, name: str, *, domain: Optional[str] = None, path: str = '/') -> None:
    #"""Deletes the cookie with the given name.

    #Due to limitations of the cookie protocol, you must pass the same
    #path and domain to clear a cookie as were used when that cookie
    #was set (but there is no way to find out on the server side
    #which values were used for a given cookie).

    #Similar to `set_cookie`, the effect of this method will not be
    #seen until the following request.
    #"""
    #expires = datetime.utcnow() - timedelta(days=365)
    #set_cookie(response, name, value='', domain=domain, path=path, expires=expires, max_age=0)



#================================================================================================================================
def main():

    print (40*"*", "opasAPISupportLib Tests", 40*"*")
    print ("Fini")

# -------------------------------------------------------------------------------------------------------
# run it!

if __name__ == "__main__":
    print ("Running in Python %s" % sys.version_info[0])
    
    sys.path.append(r'E:/usr3/GitHub/openpubarchive/app')
    sys.path.append(r'E:/usr3/GitHub/openpubarchive/app/config')
    sys.path.append(r'E:/usr3/GitHub/openpubarchive/app/libs')
    for n in sys.path:
        print (n)

    # Spot testing during Development
    #metadataGetContents("IJP", "1993")
    #getAuthorInfo("Tuck")
    #metadataGetVolumes("IJP")
    #authorsGetAuthorInfo("Tuck")
    #authorsGetAuthorPublications("Tuck", limit=40, offset=0)    
    #databaseGetMostCited(limit=10, offset=0)
    #getArticleData("PAQ.073.0005A")
    #databaseWhatsNew()
    # docstring tests
    # get_list_of_most_downloaded()
    # sys.exit(0)
    logger = logging.getLogger(__name__)
    # extra logging for standalong mode 
    logger.setLevel(logging.DEBUG)
    # create console handler and set level to debug
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    # create formatter
    formatter = logging.Formatter('%(asctime)s %(name)s %(lineno)d - %(levelname)s %(message)s')    
    # add formatter to ch
    ch.setFormatter(formatter)
    # add ch to logger
    logger.addHandler(ch)
    
    import doctest
    doctest.testmod()    
    main()
