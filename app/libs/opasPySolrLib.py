#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=C0321,C0103,C0301,E1101,C0303,E1004,C0330,R0915,R0914,W0703,C0326

"""
opasPySolrLib

This library is meant to support query to Solr

"""
__author__      = "Neil R. Shapiro"
__copyright__   = "Copyright 2019, Psychoanalytic Electronic Publishing"
__license__     = "Apache 2.0"
__version__     = "2020.1118.1"
__status__      = "Development"

import re
import logging
logger = logging.getLogger(__name__)
import time
from datetime import datetime

import sys
sys.path.append('./solrpy')
import solrpy as solr
from xml.sax import SAXParseException
import lxml

import localsecrets
from localsecrets import TIME_FORMAT_STR

# from localsecrets import BASEURL, SOLRURL, SOLRUSER, SOLRPW, DEBUG_DOCUMENTS, SOLR_DEBUG, CONFIG, COOKIE_DOMAIN  
import starlette.status as httpCodes
from configLib.opasCoreConfig import solr_docs2, solr_authors2, solr_gloss2, solr_docs_term_search2, solr_authors_term_search2
import opasConfig 
from opasConfig import KEY_SEARCH_FIELD, KEY_SEARCH_SMARTSEARCH, KEY_SEARCH_VALUE
from configLib.opasCoreConfig import EXTENDED_CORES

import models
import opasCentralDBLib
import schemaMap
import opasGenSupportLib as opasgenlib
import opasXMLHelper as opasxmllib
import opasDocPermissions as opasDocPerm
import smartsearch
import opasQueryHelper

import pysolr

sourceDB = opasCentralDBLib.SourceInfoDB()
ocd = opasCentralDBLib.opasCentralDB()
pat_prefix_amps = re.compile("^\s*&& ")

def search(query, summaryField, highlightFields='art_authors_xml, art_title_xml, text_xml', returnStartAt=0, returnLimit=10):
    args = {
               # 'fl':summaryField,
               # 'q':'tuck*',
               'hl': 'true',
               'hl.fragsize': 125,
               'hl.fl':highlightFields,
               'rows':returnLimit,
               'hl.simplepre': '<em>',
               'hl.simplepost': '</em>'
           }

    #solr = pysolr.Solr('http://localhost:8983/solr/pepwebdocs', timeout=10)
    results = solr_docs2.search(query, **args)
    return results

#================================================================================================================
def search_text_qs(solr_query_spec: models.SolrQuerySpec,
                   extra_context_len=None,
                   req_url: str=None,
                   facet_limit=None,
                   facet_offset=None, 
                   limit=None,
                   offset=None,
                   mlt_count=None, # 0 turns off defaults for mlt, number overrides defaults, setting solr_query_spec is top priority
                   sort=None, 
                   session_info=None,
                   solr_core="pepwebdocs"
                   ):
    """
    Full-text search, via the Solr server api.

    Returns a pair of values: ret_val, ret_status.  The double return value is important in case the Solr server isn't running or it returns an HTTP error.  The 
       ret_val = a DocumentList model object
       ret_status = a status tuple, consisting of a HTTP status code and a status mesage. Default (HTTP_200_OK, "OK")

    """
    ret_val = {}
    ret_status = (200, "OK") # default is like HTTP_200_OK
    global count_anchors

    if 1:
        if solr_query_spec.solrQueryOpts is None: # initialize a new model
            solr_query_spec.solrQueryOpts = models.SolrQueryOpts()
    
        if solr_query_spec.solrQuery is None: # initialize a new model
            solr_query_spec.solrQuery = models.SolrQuery()
    
        #if authenticated is None:
            #authenticated = solr_query_spec.a
    
        if extra_context_len is not None:
            solr_query_spec.solrQueryOpts.hlFragsize = extra_context_len
        elif solr_query_spec.solrQueryOpts.hlFragsize is None or solr_query_spec.solrQueryOpts.hlFragsize < opasConfig.DEFAULT_KWIC_CONTENT_LENGTH:
            solr_query_spec.solrQueryOpts.hlFragsize = opasConfig.DEFAULT_KWIC_CONTENT_LENGTH
        #else: # for debug only
            #print (f"Fragment Size: {solr_query_spec.solrQueryOpts.hlFragsize}")
    
        if solr_query_spec.solrQueryOpts.moreLikeThisCount > 0: # this (arg based) is the priority value
            mlt = "true"
            mlt_count = solr_query_spec.solrQueryOpts.moreLikeThisCount
            if solr_query_spec.solrQueryOpts.moreLikeThisFields is None:
                mlt_fl = opasConfig.DEFAULT_MORE_LIKE_THIS_FIELDS # Later: solr_query_spec.solrQueryOpts.moreLikeThisFields
            mlt_minwl = 4
        elif mlt_count is not None and mlt_count > 0:
            # mlt_count None means "don't care, use default", mlt_count > 0: override default
            mlt = "true"
            #  use default fields though
            mlt_fl = opasConfig.DEFAULT_MORE_LIKE_THIS_FIELDS # Later: solr_query_spec.solrQueryOpts.moreLikeThisFields
            mlt_minwl = 4
        elif (opasConfig.DEFAULT_MORE_LIKE_THIS_COUNT > 0 and mlt_count is None): # if caller doesn't care (None) and default is on
            # mlt_count None means "don't care, use default", mlt_count > 0: override default
            mlt = "true"
            if mlt_count is None: # otherwise it's more than 0 so overrides the default
                mlt_count = opasConfig.DEFAULT_MORE_LIKE_THIS_COUNT
            #  use default fields though
            mlt_fl = opasConfig.DEFAULT_MORE_LIKE_THIS_FIELDS # Later: solr_query_spec.solrQueryOpts.moreLikeThisFields
            mlt_minwl = 4
        else: # otherwise no MLT, mlt_count may be intentionally set to 0, or default is off and caller didn't say
            mlt_fl = None
            mlt = "false"
            mlt_minwl = None
            mlt_count = 0
    
        if solr_query_spec.facetFields is not None:
            facet = "on"
        else:
            facet = "off"
    
        try:
            if solr_query_spec.solrQueryOpts.hlMaxAnalyzedChars < 200: # let caller configure, but not 0!
                solr_query_spec.solrQueryOpts.hlMaxAnalyzedChars = opasConfig.SOLR_HIGHLIGHT_RETURN_MIN_FRAGMENT_SIZE # opasConfig.SOLR_HIGHLIGHT_RETURN_FRAGMENT_SIZE
        except:
            solr_query_spec.solrQueryOpts.hlMaxAnalyzedChars = opasConfig.SOLR_HIGHLIGHT_RETURN_MIN_FRAGMENT_SIZE # opasConfig.SOLR_HIGHLIGHT_RETURN_FRAGMENT_SIZE
        #else: OK, leave it be!
    
        try: # must have value
            if solr_query_spec.solrQueryOpts.hlFragsize < opasConfig.DEFAULT_KWIC_CONTENT_LENGTH:
                solr_query_spec.solrQueryOpts.hlFragsize = opasConfig.DEFAULT_KWIC_CONTENT_LENGTH
        except:
            solr_query_spec.solrQueryOpts.hlFragsize = opasConfig.DEFAULT_KWIC_CONTENT_LENGTH
        else:
            pass # else, it's ok
    
        # let this be None, if no limit is set.
        if limit is not None:
            if limit < 0: # unlimited return, to bypass default
                solr_query_spec.limit = opasConfig.MAX_DOCUMENT_RECORDS_RETURNED_AT_ONCE
            else:
                solr_query_spec.limit = limit
    
        if offset is not None:
            solr_query_spec.offset = offset
    
        if sort is not None:
            solr_query_spec.solrQuery.sort = sort
    
        # q must be part of any query; this appears to be the cause of the many solr syntax errors seen. 
        if solr_query_spec.solrQuery.searchQ is None or solr_query_spec.solrQuery.searchQ == "":
            logger.error(f">>>>>> solr_query_spec.solrQuery.searchQ is {solr_query_spec.solrQuery.searchQ}.  Filter: {solr_query_spec.solrQuery.filterQ} The endpoint request was: {req_url}")
            solr_query_spec.solrQuery.searchQ = "*.*"
    
        # one last cleaning
        solr_query_spec.solrQuery.searchQ = solr_query_spec.solrQuery.searchQ.replace(" && *:*", "")
        solr_query_spec.solrQuery.filterQ = solr_query_spec.solrQuery.filterQ.replace(" && *:*", "")

    try:
        query = solr_query_spec.solrQuery.searchQ
        solr_param_dict = { 
                            # "q": solr_query_spec.solrQuery.searchQ,
                            "fq": solr_query_spec.solrQuery.filterQ,
                            "q.op": solr_query_spec.solrQueryOpts.qOper, 
                            # "debugQuery": solr_query_spec.solrQueryOpts.queryDebug or localsecrets.SOLR_DEBUG,
                            # "defType" : solr_query_spec.solrQueryOpts.defType,
                            "fl" : solr_query_spec.returnFields,         
                            "hl" : solr_query_spec.solrQueryOpts.hl, 
                            "hl.multiterm" : solr_query_spec.solrQueryOpts.hlMultiterm,
                            "hl.fl" : solr_query_spec.solrQueryOpts.hlFields,
                            "hl.usePhraseHighlighter" : solr_query_spec.solrQueryOpts.hlUsePhraseHighlighter, 
                            "hl.snippets" : solr_query_spec.solrQueryOpts.hlMaxKWICReturns,
                            "hl.fragsize" : solr_query_spec.solrQueryOpts.hlFragsize, 
                            "hl.maxAnalyzedChars" : solr_query_spec.solrQueryOpts.hlMaxAnalyzedChars,
                            "facet" : facet,
                            "facet.field" : solr_query_spec.facetFields, #["art_lang", "art_authors"],
                            "facet.mincount" : solr_query_spec.facetMinCount,
                            #hl_method="unified",  # these don't work
                            #hl_encoder="HTML",
                            "mlt" : mlt,
                            "mlt.fl" : mlt_fl,
                            "mlt.count" : mlt_count,
                            "mlt.minwl" : mlt_minwl,
                            "mlt.interestingTerms" : "list",
                            "rows" : solr_query_spec.limit,
                            "start" : solr_query_spec.offset,
                            "sort" : solr_query_spec.solrQuery.sort,
                            "hl_simple_pre" : opasConfig.HITMARKERSTART,
                            "hl_simple_post" : opasConfig.HITMARKEREND        
        }

        args = {
                   # 'fl':summaryField,
                   # 'q':'tuck*',
                   'hl': 'true',
                   'hl.fragsize': 125,
                   'hl.fl':highlightFields,
                   'rows':returnLimit,
                   'hl.simplepre': '<em>',
                   'hl.simplepost': '</em>'
               }

        
    except Exception as e:
        logger.error(f"Solr Param Assignment Error {e}")

    # add additional facet parameters from faceSpec
    #for key, value in solr_query_spec.facetSpec.items():
        #if key[0:1] != "f":
            #continue
        #else:
            #solr_param_dict[key] = value
    
    # Solr sometimes returns an SAX Parse error because of Nones!
    # just in case, get rid of all Nones
    # solr_param_dict = {k: v for k, v in solr_param_dict.items() if v is not None}

    #allow core parameter here
    if solr_core is None:
        if solr_query_spec.core is not None:
            try:
                solr_core = EXTENDED_CORES.get(solr_query_spec.core, None)
            except Exception as e:
                detail=f"Bad Extended Request. Core Specification Error. {e}"
                logger.error(detail)
                ret_val = models.ErrorReturn(httpcode=400, error="Core specification error", error_description=detail)
            else:
                if solr_core is None:
                    detail=f"Bad Extended Request. Unknown core specified."
                    logger.warning(detail)
                    ret_val = models.ErrorReturn(httpcode=400, error="Core specification error", error_description=detail)
        else:
            solr_query_spec.core = "pepwebdocs"
            solr_core = solr_docs2
    else:
        try:
            solr_core = EXTENDED_CORES.get(solr_core, None)
        except Exception as e:
            detail=f"Bad Extended Request. Core Specification Error. {e}"
            logger.error(detail)
            ret_val = models.ErrorReturn(httpcode=400, error="Core specification error", error_description=detail)
        else:
            if solr_core is None:
                detail=f"Bad Extended Request. Unknown core specified."
                logger.warning(detail)
                ret_val = models.ErrorReturn(httpcode=400, error="Core specification error", error_description=detail)

    try:
        results = solr_core.search(query, **solr_param_dict)

    except solr.SolrException as e:
        if e is None:
            ret_val = models.ErrorReturn(httpcode=httpCodes.HTTP_400_BAD_REQUEST, error="Solr engine returned an unknown error", error_description=f"Solr engine returned error without a reason")
            ret_status = (e.httpcode, None) # e has type <class 'solrpy.core.SolrException'>,with useful elements of httpcode, reason, and body
            logger.error(f"Solr Runtime Search Error (a): {e.reason}")
            logger.error(e.body)
        elif e.reason is not None:
            ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Solr engine returned an unknown error", error_description=f"Solr engine returned error {e.httpcode} - {e.reason}")
            ret_status = (e.httpcode, e) # e has type <class 'solrpy.core.SolrException'>,with useful elements of httpcode, reason, and body
            logger.error(f"Solr Runtime Search Error (b): {e.reason}")
            logger.error(e.body)
        else:
            ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Search syntax error", error_description=f"There's an error in your input (no reason supplied)")
            ret_status = (e.httpcode, e) # e has type <class 'solrpy.core.SolrException'>,with useful elements of httpcode, reason, and body
            logger.error(f"Solr Runtime Search Error (c): {e.httpcode}")
            logger.error(e.body)
        
    except SAXParseException as e:
        ret_val = models.ErrorReturn(httpcode=httpCodes.HTTP_400_BAD_REQUEST, error="Search syntax error", error_description=f"{e.getMessage()}")
        ret_status = (httpCodes.HTTP_400_BAD_REQUEST, e) # e has type <class 'solrpy.core.SolrException'>, with useful elements of httpcode, reason, and body, e.g.,
        logger.error(f"Solr Runtime Search Error (parse): {ret_val}. Params sent: {solr_param_dict}")

    except AttributeError as e:
        logger.error(f"Attribute Error: {e}")
    
    except Exception as e:
        ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Search syntax error", error_description=f"There's an error in your input (no reason supplied)")
        ret_status = (httpCodes.HTTP_400_BAD_REQUEST, e) # e has type <class 'solrpy.core.SolrException'>, with useful elements of httpcode, reason, and body, e.g.,
        logger.error(f"Solr Runtime Search Error (syntax): {e.httpcode}. Params sent: {solr_param_dict}")
        logger.error(e.body)
                                
    else: #  search was ok
        try:
            logger.info(f"Search Ok. Result Size:{results._numFound}; Search:{solr_query_spec.solrQuery.searchQ}; Filter:{solr_query_spec.solrQuery.filterQ}")
            scopeofquery = [solr_query_spec.solrQuery.searchQ, solr_query_spec.solrQuery.filterQ]
    
            if ret_status[0] == 200: 
                documentItemList = []
                rowCount = 0
                # rowOffset = 0
                #if solr_query_spec.fullReturn:
                    ## if we're not authenticated, then turn off the full-text request and behave as if we didn't try
                    #if not authenticated: # and file_classification != opasConfig.DOCUMENT_ACCESS_FREE:
                        ## can't bring back full-text
                        #logger.warning("Fulltext requested--by API--but not authenticated.")
                        #solr_query_spec.fullReturn = False
                        
                # try checking PaDS for authenticated; if false, no need to check permits
                try:
                    if session_info is not None:
                        if session_info.authenticated == False:
                            logger.debug("User is not authenticated.  Permit optimization enabled.")
                        else:
                            logger.debug("User is authenticated.  Permit optimization disabled.")
                    else: # no session info provided.  Set it to defaults, non-authenticated
                        logger.debug("No session info object provided.")
                        
                except Exception as e:
                    #  no session info...what to do?
                    logger.debug(f"No session info to perform optimizations {e}")
                    
                for result in results.results:
                    # reset anchor counts for full-text markup re.sub
                    count_anchors = 0
                    record_count = len(results.results)
                    # authorIDs = result.get("art_authors", None)
                    documentListItem = models.DocumentListItem()
                    documentListItem = get_base_article_info_from_search_result(result, documentListItem)
                    documentID = documentListItem.documentID
                    # sometimes, we don't need to check permissions
                    # Always check if fullReturn is selected
                    # Don't check when it's not and a large number of records are requested (but if fullreturn is requested, must check)
                    if record_count < opasConfig.MAX_RECORDS_FOR_ACCESS_INFO_RETURN or solr_query_spec.fullReturn:
                        #print(f"Precheck: Session info archive access: {session_info.authorized_peparchive}")
                        opasDocPerm.get_access_limitations( doc_id=documentListItem.documentID, 
                                                            classification=documentListItem.accessClassification, 
                                                            year=documentListItem.year,
                                                            doi=documentListItem.doi, 
                                                            session_info=session_info, 
                                                            documentListItem=documentListItem,
                                                            fulltext_request=solr_query_spec.fullReturn
                                                           ) # will updated accessLimited fields in documentListItem
                        #print(f"Postcheck: Session info archive access: {session_info.authorized_peparchive}")
    
                    documentListItem.score = result.get("score", None)               
                    try:
                        text_xml = results.highlighting[documentID].get("text_xml", None)
                    except:
                        text_xml = None
    
                    if text_xml is None: # try getting it from para
                        try:
                            text_xml = results.highlighting[documentID].get("para", None)
                        except:
                            try:
                                text_xml = result["text_xml"]
                            except:
                                text_xml = result.get("para", None)
    
                    if text_xml is not None and type(text_xml) != list:
                        text_xml = [text_xml]
    
                    # do this before we potentially clear text_xml if no full text requested below
                    if solr_query_spec.abstractReturn:
                        omit_abstract = False
                        if opasConfig.ACCESS_ABSTRACT_RESTRICTION:
                            if session_info is not None:
                                if not session_info.authenticated:
                                    # experimental - remove abstract if not authenticated, per DT's requirement
                                    omit_abstract = True
                            else: # no session info, omit abstract
                                omit_abstract = True
                        
                        documentListItem = get_excerpt_from_search_result(result, documentListItem, solr_query_spec.returnFormat, omit_abstract=omit_abstract)
    
                    documentListItem.kwic = "" # need this, so it doesn't default to Nonw
                    documentListItem.kwicList = []
                    # no kwic list when full-text is requested.
                    if text_xml is not None and not solr_query_spec.fullReturn and solr_query_spec.solrQueryOpts.hl == 'true':
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
                        # we don't need fulltext
                        text_xml = None
                        #print ("Document Length: {}; Matches to show: {}".format(len(textXml), len(kwicList)))
                    else: # either fulltext requested, or no document, we don't need kwic
                        kwic_list = []
                        kwic = ""  # this has to be "" for PEP-Easy, or it hits an object error.  
    
                    if kwic != "": documentListItem.kwic = kwic
                    if kwic_list != []: documentListItem.kwicList = kwic_list
    
                    # see if this article is an offsite article
                    offsite = result.get("art_offsite", False)
                    # ########################################################################
                    # This is the room where where full-text return HAPPENS
                    # ########################################################################
                    if solr_query_spec.fullReturn and not documentListItem.accessLimited and not offsite:
                        documentListItem = get_fulltext_from_search_results(result=result,
                                                                            text_xml=text_xml,
                                                                            format_requested=solr_query_spec.returnFormat,
                                                                            return_options=solr_query_spec.returnOptions, 
                                                                            page=solr_query_spec.page,
                                                                            page_offset=solr_query_spec.page_offset,
                                                                            page_limit=solr_query_spec.page_limit,
                                                                            documentListItem=documentListItem)

                        #  test remove glossary..for my tests, not for stage/production code.
                        # Note: the question mark before the first field in search= matters
                        #  e.g., http://development.org:9100/v2/Documents/Document/JCP.001.0246A/?return_format=XML&search=%27?fulltext1="Evenly%20Suspended%20Attention"~25&limit=10&facetmincount=1&facetlimit=15&sort=score%20desc%27
                        # documentListItem.document = opasxmllib.xml_remove_tags_from_xmlstr(documentListItem.document,['impx']) 
                        try:
                            matches = re.findall(f"class='searchhit'|{opasConfig.HITMARKERSTART}", documentListItem.document)
                            documentListItem.term = f"SearchHits({solr_query_spec.solrQuery.searchQ})"
                            documentListItem.termCount = len(matches)
                        except Exception as e:
                            logger.warning(f"Exception.  Could not count matches. {e}")
                        
                    else: # by virtue of not calling that...
                        # no full-text if accessLimited or offsite article
                        # free up some memory, since it may be large
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
    
                    similarityMatch = None
                    if mlt_count > 0:
                        if results.moreLikeThis[documentID] is not None:
                            similarityMatch = {}
                            # remove text
                            similarityMatch["similarDocs"] = {}
                            similarityMatch["similarDocs"][documentID] = []
                            for n in results.moreLikeThis[documentID]:
                                likeThisListItem = models.DocumentListItem()
                                #n["text_xml"] = None
                                n = get_base_article_info_from_search_result(n, likeThisListItem)                    
                                similarityMatch["similarDocs"][documentID].append(n)
    
                            similarityMatch["similarMaxScore"] = results.moreLikeThis[documentID].maxScore
                            similarityMatch["similarNumFound"] = results.moreLikeThis[documentID].numFound
                            # documentListItem.moreLikeThis = results.moreLikeThis[documentID]
    
                    if similarityMatch is not None: documentListItem.similarityMatch = similarityMatch
                    
                    #parent_tag = result.get("parent_tag", None)
                    #if parent_tag is not None:
                        #documentListItem.docChild = {}
                        #documentListItem.docChild["id"] = result.get("id", None)
                        #documentListItem.docChild["parent_tag"] = parent_tag
                        #documentListItem.docChild["para"] = result.get("para", None)
                        #documentListItem.docChild["lang"] = result.get("lang", None)
                        #documentListItem.docChild["para_art_id"] = result.get("para_art_id", None)
                    #else:
                        #documentListItem.docChild = None
    
                    sort_field = None
                    if solr_query_spec.solrQuery.sort is not None:
                        try:
                            sortby = re.search("(?P<field>[a-z_]+[1-9][0-9]?)[ ]*?", solr_query_spec.solrQuery.sort)
                        except Exception as e:
                            sort_field = None
                        else:
                            if sortby is not None:
                                sort_field = sortby.group("field")
    
                    documentListItem.score = result.get("score", None)
                    documentListItem.rank = rowCount + 1
                    if sort_field is not None:
                        if sort_field == "art_cited_all":
                            documentListItem.rank = result.get("art_cited_all", None) 
                        elif sort_field == "score":
                            documentListItem.rank = result.get("score", None)
                        else:
                            documentListItem.rank = result.get(sort_field, None)
                            
                            
                    rowCount += 1
                    # add it to the set!
                    documentItemList.append(documentListItem)
                    #TODO - we probably don't need this.
                    if solr_query_spec.limit is not None:
                        if rowCount > solr_query_spec.limit:
                            break
    
                try:
                    facet_counts = results.facet_counts
                except:
                    facet_counts = None
    
            if req_url is None:
                req_url = solr_query_spec.urlRequest
    
            # Moved this down here, so we can fill in the Limit, Page and Offset fields based on whether there
            #  was a full-text request with a page offset and limit
            # Solr search was ok
            responseInfo = models.ResponseInfo(count = len(results.results),
                                               fullCount = results._numFound,
                                               totalMatchCount = results._numFound,
                                               description=solr_query_spec.solrQuery.semanticDescription, 
                                               limit = solr_query_spec.limit,
                                               offset = solr_query_spec.offset,
                                               page = solr_query_spec.page, 
                                               listType="documentlist",
                                               scopeQuery=[scopeofquery], 
                                               fullCountComplete = solr_query_spec.limit >= results._numFound,
                                               solrParams = results._params,
                                               facetCounts=facet_counts,
                                               #authenticated=authenticated, 
                                               request=f"{req_url}",
                                               core=solr_query_spec.core, 
                                               timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                               )
   
            # responseInfo.count = len(documentItemList)
    
            documentListStruct = models.DocumentListStruct( responseInfo = responseInfo, 
                                                            responseSet = documentItemList
                                                            )
    
            documentList = models.DocumentList(documentList = documentListStruct)
    
            ret_val = documentList
            
        except Exception as e:
            logger.error(f"Problem with query results processing {e}")
            

    return ret_val, ret_status

#-----------------------------------------------------------------------------
def metadata_get_videos(src_type=None, pep_code=None, limit=opasConfig.DEFAULT_LIMIT_FOR_METADATA_LISTS, offset=0):
    """
    Fill out a sourceInfoDBList which can be used for a getSources return, but return individual 
      videos, as is done for books.  This provides more information than the 
      original API which returned video "journals" names.
      
    Authorizations are not checked or returned (thus no session id is needed)

    """
    source_info_dblist = []
    total_count = 0
    ret_val = {}
    return_status = (200, "OK")

    if pep_code is not None:
        q_str = "art_sourcetype:video* AND art_sourcecode:{}".format(pep_code)
    else:
        q_str = "art_sourcetype:video*"
        
    try:
        logger.info(f"Solr Query: q={q_str}")
        query = q_str
        args = {
                   'fl':opasConfig.DOCUMENT_ITEM_VIDEO_FIELDS,
                   # 'q':'tuck*',
                   'rows':limit,
                   'start': offset,
                   'sort':"art_citeas_xml asc",
                   #'sort.order':'asc'
               }

        srcList = solr_docs2.search(query, **args)

    except Exception as e:
        logger.error("metadataGetVideos Error: {}".format(e))
        ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Search syntax error", error_description=f"There's an error in your input (no reason supplied)")
        ret_status = (httpCodes.HTTP_400_BAD_REQUEST, e) # e has type <class 'solrpy.core.SolrException'>, with useful elements of httpcode, reason, and body, e.g.,
        logger.error(f"Solr Runtime Search Error (syntax): {e.httpcode}. Params sent: {solr_param_dict}")
        logger.error(e.body)
    else:
        # count = len(srcList.results)
        total_count = srcList.raw_response['response']['numFound']
    
        for result in srcList.docs:
            source_info_record = {}
            authors = result.get("art_authors")
            if authors is None:
                source_info_record["author"] = None
            elif len(authors) > 1:
                source_info_record["author"] = "; ".join(authors)
            else:    
                source_info_record["author"] = authors[0]
    
            source_info_record["src_code"] = result.get("art_sourcecode")
            source_info_record["ISSN"] = result.get("art_issn")
            source_info_record["documentID"] = result.get("art_id")
            try:
                source_info_record["title"] = result.get("title")
            except:
                source_info_record["title"] = ""
    
            source_info_record["art_citeas"] = result.get("art_citeas_xml")
            source_info_record["pub_year"] = result.get("art_year")
            source_info_record["bib_abbrev"] = result.get("art_sourcetitleabbr")  # error in get field, fixed 2019.12.19
            try:
                source_info_record["language"] = result.get("art_lang")
            except:
                source_info_record["language"] = "EN"
    
            logger.debug("metadataGetVideos: %s", source_info_record)
            source_info_dblist.append(source_info_record)

    return total_count, source_info_dblist, ret_val, return_status

#-----------------------------------------------------------------------------
def database_get_whats_new(days_back=14,
                           limit=opasConfig.DEFAULT_LIMIT_FOR_WHATS_NEW,
                           req_url:str=None,
                           source_type="journal",
                           offset=0,
                           session_info=None):
    """
    Return what JOURNALS have been updated in the last week

    >>> result = database_get_whats_new()

    """    
    field_list = "art_id, title, art_vol, art_iss, art_sourcecode, art_sourcetitlefull, art_sourcetitleabbr, file_last_modified, timestamp, art_sourcetype"
    sort_by = "file_last_modified desc"
    ret_val = None

    # two ways to get date, slightly different meaning: timestamp:[NOW-{days_back}DAYS TO NOW] AND file_last_modified:[NOW-{days_back}DAYS TO NOW]
    try:
        query = f"file_last_modified:[NOW-{days_back}DAYS TO NOW] AND art_sourcetype:{source_type}"
        logger.info(f"Solr Query: q={query}")

        args = {
            "fl": field_list,
            "fq": "{!collapse field=art_sourcecode max=art_year_int}",
            "sort": sort_by,
            "rows": limit,
            "start": offset
        }

        results = solr_docs2.search(query, **args)

    except Exception as e:
        logger.error(f"Solr Search Exception: {e}")
        response_info = models.ResponseInfo( count = 0,
                                             fullCount = 0,
                                             limit = limit,
                                             offset = offset,
                                             listType="newlist",
                                             fullCountComplete = False,
                                             request=f"{req_url}",
                                             timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                             )
        response_info.count = 0
        whats_new_list_items = []
        whats_new_list_struct = models.WhatsNewListStruct( responseInfo = response_info, 
                                                           responseSet = whats_new_list_items
                                                           )
        ret_val = models.WhatsNewList(whatsNew = whats_new_list_struct)
    else:
        num_found = results.raw_response['response']['numFound']
        whats_new_list_items = []
        row_count = 0
        already_seen = []
        for result in results.docs:
            PEPCode = result.get("art_sourcecode", None)
            #if PEPCode is None or PEPCode in ["SE", "GW", "ZBK", "IPL"]:  # no books
                #continue
            src_type = result.get("art_sourcetype", None)
            if src_type != "journal":
                continue
    
            volume = result.get("art_vol", None)
            issue = result.get("art_iss", "")
            year = result.get("art_year", None)
            abbrev = result.get("art_sourcetitleabbr", None)
            src_title = result.get("art_sourcetitlefull", None)
            
            updated = result.get("file_last_modified", None)
            updated = datetime.strptime(updated,'%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d')
            if abbrev is None:
                abbrev = src_title
            display_title = abbrev + " v%s.%s (%s) " % (volume, issue, year)
            if display_title in already_seen:
                continue
            else:
                already_seen.append(display_title)
            volume_url = "/v1/Metadata/Contents/%s/%s" % (PEPCode, issue)
    
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
    
        response_info = models.ResponseInfo( count = len(results.docs),
                                             fullCount = num_found,
                                             limit = limit,
                                             offset = offset,
                                             listType="newlist",
                                             fullCountComplete = limit >= num_found,
                                             request=f"{req_url}",
                                             timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                             )

        response_info.count = len(whats_new_list_items)
    
        whats_new_list_struct = models.WhatsNewListStruct( responseInfo = response_info, 
                                                           responseSet = whats_new_list_items
                                                           )
    
        ret_val = models.WhatsNewList(whatsNew = whats_new_list_struct)

    return ret_val   # WhatsNewList

def metadata_get_volumes(source_code=None,
                         source_type=None,
                         req_url: str=None 
                         #limit=1,
                         #offset=0
                        ):
    """
    Return a list of volumes
      - for a specific source_code (code),
      - OR for a specific source_type (e.g. journal)
      - OR if source_code and source_type are not specified, bring back them all
      
    This is a new version (08/2020) using Solr pivoting rather than the OCD database.
      
    """
    # returns multiple gw's and se's, 139 unique volumes counting those (at least in 2020)
    # works for journal, videostreams have more than one year per vol.
    # works for books, videostream vol numbers
    #results = solr_docs.query( q = f"art_sourcecode:{pep_code} && art_year:{year}",  
                                #fields = "art_sourcecode, art_vol, art_year",
                                #sort="art_sourcecode, art_year", sort_order="asc",
                                #fq="{!collapse field=art_vol}",
                                #rows=limit, start=offset
                                #)
    
    distinct_return = "art_sourcecode, art_vol, art_year, art_sourcetype"
    limit = 6
    count = 0
    ret_val = None
    # normalize source type
    if source_type is not None: # none is ok
        source_type = opasConfig.normalize_val(source_type, opasConfig.VALS_SOURCE_TYPE, None)
    
    q_str = "bk_subdoc:false"
    if source_code is not None:
        q_str += f" && art_sourcecode:{source_code}"
    if source_type is not None:
        q_str += f" && art_sourcetype:{source_type}"
    facet_fields = ["art_vol", "art_sourcecode"]
    facet_pivot = "art_sourcecode,art_year,art_vol" # important ...no spaces!
    try:
        logger.info(f"Solr Query: q={q_str} facet='on'")
        args = {"fq":"*:*", 
                "fields" : distinct_return,
                "sort":"art_sourcecode ASC, art_year ASC",
                "facet":"on", 
                "facet.fields" : facet_fields, 
                "facet.pivot" : facet_pivot,
                "facet.mincount":1,
                "facet.sort":"art_year asc", 
                "rows":limit, 
                #"start":offset
              }

        result = solr_docs2.search(q_str, **args)
        
        facet_pivot = result.facet_counts["facet_pivot"][facet_pivot]
        #ret_val = [(piv['value'], [n["value"] for n in piv["pivot"]]) for piv in facet_pivot]

        response_info = models.ResponseInfo( count = count,
                                             fullCount = count,
                                             #limit = limit,
                                             #offset = offset,
                                             listType="volumelist",
                                             fullCountComplete = (limit == 0 or limit >= count),
                                             request=f"{req_url}",
                                             timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                             )

        
        volume_item_list = []
        volume_dup_check = {}
        for m1 in facet_pivot:
            journal_code = m1["value"] # pepcode
            seclevel = m1["pivot"]
            for m2 in seclevel:
                secfield = m2["field"] # year
                secval = m2["value"]
                thirdlevel = m2["pivot"]
                for m3 in thirdlevel:
                    thirdfield = m3["field"] # vol
                    thirdval = m3["value"]
                    PEPCode = journal_code
                    year = secval
                    vol = thirdval
                    count = m3["count"]
                    pep_code_vol = PEPCode + vol
                    # if it's a journal, Supplements are not a separate vol, they are an issue.
                    if pep_code_vol[-1] == "S" and journal_code not in opasConfig.BOOK_CODES_ALL:
                        pep_code_vol = pep_code_vol[:-1]
                    cur_code = volume_dup_check.get(pep_code_vol)
                    if cur_code is None:
                        volume_dup_check[pep_code_vol] = [year]
                        volume_list_item = models.VolumeListItem(PEPCode=PEPCode,
                                                                 vol=vol,
                                                                 year=year,
                                                                 years=[year],
                                                                 count=count
                        )
                        volume_item_list.append(volume_list_item)
                    else:
                        volume_dup_check[pep_code_vol].append(year)
                        if year not in volume_list_item.years:
                            volume_list_item.years.append(year)
                        volume_list_item.count += count

                
    except Exception as e:
        logger.error(f"Error: {e}")
    else:
        response_info.count = len(volume_item_list)
        response_info.fullCount = len(volume_item_list)
    
        volume_list_struct = models.VolumeListStruct( responseInfo = response_info, 
                                                      responseSet = volume_item_list
                                                      )
    
        volume_list = models.VolumeList(volumeList = volume_list_struct)
    
        ret_val = volume_list
        
    return ret_val


if __name__ == "__main__":

    results = search('art_title_xml:impossible', 'art_title_xml', 'art_title_xml')
    
    #results = solr_authors_term_search2(terms_fl="art_author_id",
                                       #terms_limit=limit,  # this causes many regex expressions to fail
                                       #terms_regex=author_partial.lower() + ".*",
                                       #terms_sort=author_order  # index or count
                                       #)

