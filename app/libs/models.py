#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=C0321,C0103,C0301,E1101,C0303,E1004,C0330,R0915,R0914,W0703,C0326

__author__      = "Neil R. Shapiro"
__copyright__   = "Copyright 2019, Psychoanalytic Electronic Publishing"
__license__     = "Apache 2.0"
__version__     = "2019.0617.1"
__status__      = "Development"

import sys
sys.path.append('../libs')

import re
import os.path

import time
import datetime
from datetime import datetime
from typing import List, Generic, TypeVar, Optional
import opasConfig

from enum import Enum

class ExtendedEnum(Enum):
    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))
    
from pydantic import BaseModel, Schema, Field
# from pydantic.types import EmailStr
from modelsOpasCentralPydantic import User
#from opasCentralDBLib import opasCentralDB

#-------------------------------------------------------
#
# Detail level schema structures
#
#-------------------------------------------------------
OpasDB = TypeVar('OpasDB')   
  
#-------------------------------------------------------
# Enums
#-------------------------------------------------------
class ListTypeEnum(Enum):
    volumelist = "volumelist"
    documentList = "documentlist"
    advancedSearchList = "advancedsearchlist"
    authorPubList = "authorpublist"
    authorIndex = "authorindex"
    imageURLList = "imageurllist"
    licenseInfo = "licenseinfo"
    sourceInfoList = "sourceinfolist"
    whatsNewList = "newlist"
    mostCitedList = "mostcited"
    mostViewedList = "mostviewed"
    searchAnalysisList = "srclist"
    TermIndex = "termindex"
    reportList = "reportlist"
    
class ReportTypeEnum(str, Enum):
    sessionLog = "Session-Log"
    userSearches = "User-Searches"
    documentViews = "Document-View-Stat"
    documentViewLog = "Document-View-Log"
    #opasLogs = "Opas-Error-Logs"
    
class TermTypeIDEnum(str, ExtendedEnum):
    termid = "ID"
    termname = "Name"
    termgroup = "Group"
    
class QueryParserTypeEnum(Enum):
    edismax = "edismax"
    dismax = "dismax"
    standard = "lucene"
    lucene = "lucene"
    
class SearchModeEnum(Enum):
    searchMode = "Searching"
    documentFetchMode = "DocumentFetch"
    moreLikeTheseMode = "MoreLikeThese"
    queryAnalysisMode = "QueryAnalysis"
   
class TimePeriod(Enum):
    five = '5'
    ten = '10'
    twenty = '20'
    alltime = 'all'

#-------------------------------------------------------
# Error Return classes [may not be used, switched to exceptions]
#-------------------------------------------------------
class ErrorReturn(BaseModel):
    httpcode: int = Schema(200, title="HTTP code")
    error: str = Schema(None, title="Error class or title")
    error_description: str = Schema(None, title="Error description")

#-------------------------------------------------------
# Status return structure, standard part of most models
#-------------------------------------------------------
class ResponseInfo(BaseModel):
    count: int = Schema(0, title="The number of returned items in the accompanying ResponseSet list.")
    limit: int = Schema(0, title="The limit set by the API client for the ResponseSet list.")
    offset: int = Schema(None, title="The offset the ResponseSet list begins as requested by the client to index into the full set of results, i.e., for paging through the full set.")
    page: int = Schema(None, title="If the request for a document was for a specific page number, the page number is listed here.  Offset will then reflect the relative page number from the start of the document.")
    fullCount: int = Schema(None, title="The number of items that could be returned without a limit set.")
    fullCountComplete: bool = Schema(None, title="How many matches 'theoretically' matched, though they cannot be returned for some reason, such as a search engine limitation on returned data.")
    facetCounts: dict = Schema(None, title="A dictionary of requested facet information (counts of results mapped for specified fields")
    totalMatchCount: int = Schema(None, title="The number of items in the complete match set that can be retrieved and paged through.")  # used in PEPEasy paging controls
    listLabel: str = Schema(None, title="Descriptive title of data return for SourceInfoList, e.g., Book List, Journal List, Video List. Should be used elsewhere too.")
    listType: ListTypeEnum = Schema(None, title="ListTypeEnum based identifier of the return structure, e.g., 'documentList'.")
    supplementalInfo: dict = Schema(None, title="Additional info supplied based on the endpoint")
    scopeQuery: list = Schema(None, title="The query strings applied: [query_string, filter_string]")
    description: str = Schema(None, title="A semantic description explaining the action/response")
    request: str = Schema(None, title="The URL request (endpoint) that resulted in this response.")
    core: str = Schema(None, title="The Solr Core classname used (e.g., docs, authors).")
    solrParams: dict = Schema(None, title="A dictionary based set of the parameters passed to the Solr search engine for this request.")
    errors: ErrorReturn = Schema(None, title="Any Error information")
    dataSource: str = Schema(None, title="Version of the API server software")
    authenticated: bool = Schema(None, title="If request was processed as authenticated")
    timeStamp: str = Schema(None, title="Server timestamp of return data.")   

#-------------------------------------------------------
# Simple API Status class
#-------------------------------------------------------
class APIStatusItem(BaseModel):
    opas_version: str = Schema(None, title="Version of OPAS")
    timeStamp: str = Schema(None, title="Current time")
    
#-------------------------------------------------------
# General Data Encapsulation classes
#-------------------------------------------------------
class AccessLimitations(BaseModel):
    accessLimited: bool = Schema(True, title="True if the data can not be provided for this user")
    accessLimitedCurrentContent: bool = Schema(False, title="True if the data is considered Current Content (embargoed)")
    accessLimitedReason: str = Schema(None, title="Explanation of limited access status")
    accessLimitedDescription: str = Schema(None, title="Description of why access is limited")
    accessLimitedPubLink: str = Schema(None, title="Link to publisher") 
    doi: str = Schema(None, title="Document Object Identifier, without base URL")
    
#-------------------------------------------------------
# Data Return classes
#-------------------------------------------------------
class AlertListItem(BaseModel):
    alertName: str
    alertSubscribeStatus: bool
    alertSubscribeDate: str
    action: str = Schema(None, title="")

class AlertListStruct(BaseModel):
    responseInfo: ResponseInfo 
    responseSet: List[AlertListItem] = []

class AlertList(BaseModel):
    alertList: AlertListStruct

#-------------------------------------------------------
class authorInfo(BaseModel):
    first: str = Schema(None, title="First name")
    middle: str = Schema(None, title="Middle name")
    last: str = Schema(None, title="Last name")
    title: str = Schema(None, title="Prename title (Mr. Mrs. Dr.") 
    affil: str = Schema(None, title="Affiliation")
    
class authorList(BaseModel):
    authorList: List[authorInfo] = []   

#-------------------------------------------------------

class AuthorPubListItem(BaseModel):
    authorID: str = Schema(None, title="Author ID as indexed by the system.")
    documentID: str = Schema(None, title="Doc ID for this publication by the author.")
    documentRef: str = Schema(None, title="The bibliographic form presentation of the information about the document, as in the 'citeas' area or reference sections (text-only).")
    documentRefHTML: str = Schema(None, title="Same as documentRef but in HTML.")
    year: str = Schema(None, title="Year of publication of this list item.")
    documentURL: str = Schema(None, title="API Endpoint URL (minus base) to access this document.")
    score: float = None

class AuthorPubListStruct(BaseModel):
    responseInfo: ResponseInfo 
    responseSet: List[AuthorPubListItem] = []

class AuthorPubList(BaseModel):
    authorPubList: AuthorPubListStruct

#-------------------------------------------------------

class AuthorIndexItem(BaseModel):
    authorID: str = Schema(None, title="Author ID as indexed by the system.")
    publicationsURL: str = Schema(None, title="Endpoint URL for this API to retrieve a list of this authors publications.")
    publicationsCount: int = Schema(None, title="The number of publications in this database by this author.")
    
class AuthorIndexStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[AuthorIndexItem] = []

class AuthorIndex(BaseModel):
    authorIndex: AuthorIndexStruct
    
#-------------------------------------------------------
class ClientConfig(BaseModel):
    """
    Dictionary to hold client configuration settings as set by the client administrator
    """
    configName: str = Schema(None, title="Unique name (within client ID) to save and retrieve configuration")
    configSettings: dict = Schema({}, title="Dictionary with all configuration settings")

#-------------------------------------------------------
class MoreLikeThisItem(BaseModel):
    documentID: str = Schema(None, title="Document ID/Locator", description="The multiple-section document ID, e.g., CPS.007B.0021A.B0012 in a biblio, or CPS.007B.0021A as a document ID.")
    

#-------------------------------------------------------
class DocumentListItem(BaseModel):
    coreName: str = Schema(None, title="Core", description="Core from which the item was retrieved")
    documentID: str = Schema(None, title="Document ID/Locator", description="The multiple-section document ID, e.g., CPS.007B.0021A.B0012 in a biblio, or CPS.007B.0021A as a document ID.")
    docType:  str = Schema(None, title="Document Type (Classification)", description="e.g., ART(article), ABS(abstract), ANN(announcement), COM(commentary), ERR(errata), PRO(profile), (REP)report, or (REV)review")
    documentRef: str = Schema(None, title="Document Ref (bibliographic)", description="The bibliographic form presentation of the information about the document, as in the 'citeas' area or reference sections (text-only).")
    documentRefHTML: str = Schema(None, title="Same as documentRef but in HTML.")
    documentMetaXML: str = Schema(None, title="Metadata content in XML, , e.g., element meta")
    documentInfoXML: str = Schema(None, title="The document meta information in XML, e.g., element artinfo")
    title: str = Schema(None, title="Document Title")
    authorMast: str = Schema(None, title="Author Names", description="The author names as displayed below the title in an article.")
    #2020-10-19, new convenience listing of author info (requires schema change to parse during load)
    authorList: list = Schema(None, title="List of individual author data parsed from documentInfoXML", description="List of individual author data parsed from documentInfoXML")
    origrx: str = Schema(None, title="Original Document (documentID)", description="Document idref (documentID) linking this to an original document, e.g, this is a translation of...")
    relatedrx: str = Schema(None, title="Closely Related Documents (documentID)", description="Document idref (documentID) associating all closely related documents to this one, e.g., this is a commentary on...")
    PEPCode: str = Schema(None, title="Source Acronym", description="Acronym-type code assigned to the document source e.g., CPS, IJP, ANIJP-EL, ZBK. (The first part of the document ID.)")
    sourceTitle: str = Schema(None, title="Source Title", description="The name of the document's source (title) in abbreviated, bibliographic format")
    sourceType:  str = Schema(None, title="Source Type", description="Journal, Book, Videostream")
    kwicList: list = Schema(None, title="Key Words in Context", description="The matched terms in the matched document context, set by server config DEFAULT_KWIC_CONTENT_LENGTH ") # a real list, seems better long term
    kwic: str = Schema(None, title="Key Words in Context", description="KWIC as text, concatenated, not a list -- the way in v1 (May be deprecated later") # 
    vol: str = Schema(None, title="Serial Publication Volume", description="The volume number of the source, can be alphanumeric")
    year: str = Schema(None, title="Serial Publication Year", description="The four digit year of publication")
    lang: str = Schema(None, title="Language", description="The primary language of this article")
    issn: str = Schema(None, title="The ISSN", description="The ISSN for the source") # 2020506 Not sure if we should include this, but we are at least already storing it at article level
    #isbn: str = Schema(None, title="The ISBN", description="The ISBN for the source") #  2020506 isbn is not stored at article level, so not now at least
    doi: str = Field(None, title="Document object identifier", description="Document object identifier, a standard id system admin by the International DOI Foundation (IDF)")
    issue: str = Schema(None, title="Serial Issue Number")
    issueSeqNbr: str = Schema(None, title="Serial Issue Sequence Number (continuous count)") 
    issueTitle: str = Schema(None, title="Serial Issue Title", description="Issues may have titles, e.g., special topic")
    newSectionName: str = Schema(None, title="Name of Serial Section Starting", description="The name of the section of the issue, appears for the first article of a section")
    pgRg: str = Schema(None, title="Page Range as Published", description="The published start and end pages of the document, separated by a dash")
    pgStart: str = Schema(None, title="Starting Page Number as Published", description="The published start page number of the document")
    pgEnd: str = Schema(None, title="Ending Page Number as Published", description="The published end page number of the document")
    abstract: str = Schema(None, title="Abstract", description="The document abstract, with markup")
    document: str = Schema(None, title="Document", description="The full-text document, with markup")
    docPagingInfo: dict = Schema(None, title="Requested document page, limit, and offset", description="The document is limited per the call: shows requested page, limit, and offset in a dict")
    # |= the dict (for now, may be better to change to model) allows flexibility in fields, but contains the below for PEP
    #    --document_page: str
    #    --document_page_limit: int
    #    --document_page_offset: int
    docLevel: int = Schema(None, title="Document level", description="Top level document=1, subdocument=2")
    docChild: dict = Schema(None, title="Child document fields", description="Fields specific to child documents (parent_tag, para)")
    # |= the dict
    #    --parent_tag: str = Schema(None, title="The parent of the nested/sub field para, when searching children directly")
    #    --para: str = Schema(None, title="The nested/sub field para, when searching children directly")
    updated: datetime = Schema(None, title="Source file update date and time", description="The date and time the source file was updated last")
    score: float = Schema(None, title="The match score", description="Solr's score for the match in the search")
    rank: float = Schema(None, title="Document's Search Rank")
    rankfield: str = Schema(None, title="Field in rank", description="Which field is in rank")
    referenceCount: str = Schema(None, title="Number of references", description="The number of references listed in the document bibliography")
    #instanceCount: int = Schema(None, title="Counts", description="Reusable field to return counts requested")
    # |- new v2 field, but removed during cleanup, better ata is in stat.
    stat: dict = Schema(None, title="Statistics", description="Reusable field to return counts requested")
    similarityMatch: dict = Schema(None, title="Information about similarity matches")
    translationSet: dict = Schema(None, title="Information about document translations and the original")
    # Search Analysis fields (and shared Glossary term)
    term: str = Schema(None, title="Search Analysis Term", description="For search analysis, the clause or term being reported")
    termCount: int = Schema(None, title="Search Analysis Term Count", description="For search analysis, the count of occurences of the clause or term being reported")
    # Glossary core specific fields
    termID: str = Schema(None, title="Term ID", description="")
    groupID: str = Schema(None, title="Group ID", description="")
    groupName: str = Schema(None, title="Group Name", description="")
    groupAlso: str = Schema(None, title="Group Also", description="")
    groupTermCount: str = Schema(None, title="Group Term Count", description="")
    sourcePrevious: str = Schema(None, title="Previous part (article)", description="Previous part (article) in a source divided into multiple articles (e.g., journals and some books)")
    sourceNext: str = Schema(None, title="Previous part (article)", description="Previous part (article) in a source divided into multiple articles (e.g., journals and some books)")
    termType: str = Schema(None, title="", description="")
    termSource: str = Schema(None, title="", description="")
    termDefPartXML: str = Schema(None, title="", description="")
    termDefRefXML: str = Schema(None, title="", description="")
    # these are not all currently used
    accessClassification: str = Schema(None, title="Document classification, e.g., Archive, Current, Free, OffSite")
    accessLimited: bool = Schema(True, title="Access is limited, preventing full-text return")
    accessLimitedReason: str = Schema(None, title="Explanation of user's access to this")
    accessLimitedDescription: str = Schema(None, title="Description of the access limitation applied")
    accessLimitedCurrentContent: bool = Schema(None, title="Access is limited by embargo to this specific content")
    accessLimitedPubLink: str = Schema(None, title="Link to the document or publisher in some cases where doc's not readable on PEP")
    
class DocumentListStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[DocumentListItem] = []

class DocumentList(BaseModel):
    documentList: DocumentListStruct

#-------------------------------------------------------
class DocumentStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[DocumentListItem] = []

# modified PEPEasy2020 works with multiple 
class Documents(BaseModel):
    """
    Contains one or more documents (or abstracts) and associated data items.
    
    Note that the current API only supports return of one full-text document at a time, though multiple
      abstracts may be returned via this structure.
      
    """
    # For the GVPi server, it returns a single object not an array of documents.
    # But that's inconsistent with the abstract return.  #ToDo Need to modify PEP-Easy and unify as a list.
    documents: DocumentListStruct

# possible submission and return structure for file items loaded 3/20/2020, subject to change
class FileItem(BaseModel):
    uploadToken: bytes
    sourceCode: str  # enough to generate a PEPCode/DocID
    sourceVol: str
    sourceYear: str
    sourcePageStart: str
    sourcePageEnd: str
    sourceType: str
    title: str
    sourceXML: bytes
    sourcePDF: bytes

class FileItemListStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[FileItem] = []

class FileItemList(BaseModel):
    fileItemList: FileItemListStruct
    
#-------------------------------------------------------
class ImageURLListItem(BaseModel):    
    PEPCode: str
    imageURL: str
    sourceType: str
    title: str

class ImageURLListStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[ImageURLListItem] = []

class ImageURLList(BaseModel):
    imageURLList: ImageURLListStruct

#-------------------------------------------------------
class ResponseInfoLoginStatus(BaseModel):
    loggedIn: bool = Schema(False, title="Whether the user is logged in or not")
    username: str = Schema(None, title="The logged in user's name")
    request: str = Schema(None, title="The URL of the request")
    #user: User = Schema(None, title="A user object for the user")
    error_message: str = Schema(None, title="If an error occurred, description")
    dataSource: str = Schema(None, title="Version of the API server software")
    timeStamp: str = Schema(None, title="Server timestamp of return data.")   

class LoginReturnItem(BaseModel):    
    session_id: str = Schema(None, title="")
    token_type: str = Schema(None, title="")
    access_token: str = Schema(None, title="")
    session_expires_time: datetime = Schema(None, title="")
    authenticated: bool = Schema(False, title="")
    keep_active: bool = Schema(False, title="Extend the token retention time")
    error_message: str = Schema(None, title="Error description if login failed")
    scope: str = Schema(None, title="")

#-------------------------------------------------------
class LicenseInfoStruct(BaseModel):
    responseInfo: ResponseInfoLoginStatus
    responseSet: LoginReturnItem = None

class LicenseStatusInfo(BaseModel):
    licenseInfo: LicenseInfoStruct 

# Classes returned by PaDS
class PadsSessionInfo(BaseModel):
    HasSubscription: bool = Schema(False, title="")
    IsValidLogon: bool = Schema(False, title="")
    IsValidUserName: bool = Schema(False, title="")
    ReasonId: int = Schema(0, title="")
    ReasonStr = Schema("", title="")
    SessionExpires: int = Schema(0, title="Session expires time")
    SessionId: str = Schema(None, title="Assigned session ID")
    # added session_started to model, not supplied
    session_start_time: datetime = Schema(datetime.now(), title="The time the session was started, not part of the model returned")
    pads_status_response: int = Schema(0, title="The status code returned by PaDS, not part of the model returned")
    pads_disposition: str = Schema(None, title="The disposition of PaDS either from error return or deduction")
    
class PadsUserInfo(BaseModel):
    UserId:int = Schema(None, title="")
    UserName:str = Schema(None, title="")
    UserType:str = Schema(None, title="")
    SubscriptionEndDate:str = Schema(None, title="")
    Branding:bool = Schema(None, title="")
    ClientSettings:Optional[dict]=Schema({}, title="Client app settings.  Type is dict.") # 
    ReasonId:int = Schema(None, title="Code corresponding to applicable HTTP error codes")
    ReasonStr:str = Schema(None, title="Description of reason for a non 200 return code")
    HasArchiveAccess:bool = Schema(False, title="User has subscription to PEP Archive")
    HasCurrentAccess:bool = Schema(False, title="User has subscription to PEP Current (rare)")
    # for dummy auth server
    Password:str = Schema(None, title="")

class PadsPermitInfo(BaseModel):
    # see https://app.swaggerhub.com/apis/nrshapiro/PEPSecure/1.03#/PermitResponse
    SessionId:str = Schema(None, title="session GUID")
    DocId:str = Schema(None, title="PEP Document Locator (Document ID: e.g., IJP.082.0215A)")
    HasArchiveAccess:bool = Schema(False, title="User has subscription to PEP Archive")
    HasCurrentAccess:bool = Schema(False, title="User has subscription to PEP Current (rare)")
    Permit:bool = Schema(False, title="True if the user has permission to view fulltext of DocId")
    ReasonId:int = Schema(None, title="Code corresponding to applicable HTTP error codes")
    StatusCode: int = Schema(None, title="status code returned ")
    ReasonStr:str = Schema(None, title="Description of reason for a non 200 return code")

#-------------------------------------------------------
class SessionInfo(BaseModel):    
    session_id: str = Schema(None, title="A generated session Identifier number the client passes in the header to identify the session")
    user_id: int = Schema(opasConfig.USER_NOT_LOGGED_IN_ID, title="User ID (numeric).  0 for unknown user.  Corresponds to the user table records")
    username: str = Schema(opasConfig.USER_NOT_LOGGED_IN_NAME, title="Registered user name, for convenience here")
    is_valid_login: bool = Schema(False, title="")
    has_subscription: bool = Schema(False, title="")
    is_valid_username: bool = Schema(False, title="")
    authenticated: bool = Schema(False, title="True if the user has been authenticated.")
    # the next field allows us to stop asking for permits
    confirmed_unauthenticated: bool = Schema(False, title="True if PaDS has replied to a permit with http code 401 unauthenticated.")
    authorized_peparchive: bool = Schema(False, title="New field to simplify permissions - if true this user has access to all of the archive.")
    authorized_pepcurrent: bool = Schema(False, title="New field to simplify permissions - if true this user has access to all of the current issues.")
    session_start: datetime = Schema(None, title="The datetime when the user started the session")
    session_end: datetime = Schema(None, title="The datetime when the user ended the session")
    session_expires_time: datetime = Schema(None, title="The limit on the user's session information without renewing")
    user_type: str = Schema("Unknown", title="User type, e.g., Admin or Individual")
    admin: bool = Schema(False, title="True if the user has been authenticated as admin.")
    api_client_id: int = Schema(0, title="Identifies the client APP, e.g., 2 for the PEP-Web client; this is used to look up the client apps unique API_KEY in the database when needed")
    # temporary, for debug
    pads_session_info: PadsSessionInfo = None
    pads_user_info: PadsUserInfo = None
    
#-------------------------------------------------------
class ServerStatusContent(BaseModel):
    article_count: int = Schema(0, title="")
    journal_count: int = Schema(0, title="")
    video_count: int = Schema(0, title="")
    book_count: int = Schema(0, title="")
    figure_count: int = Schema(0, title="")
    year_count: int = Schema(0, title="")
    year_first: int = Schema(0, title="")
    year_last: int = Schema(0, title="")
    vol_count: int = Schema(0, title="")   
    page_count: int = Schema(0, title="")
    page_height_feet: float = Schema(0, title="")
    page_weight_tons: float = Schema(0, title="")
    source_count: dict = Schema(None, title="")
    description_html: str = Schema(None, title="")
    source_count_html: str = Schema(None, title="")

class ServerStatusItem(BaseModel):
    db_server_ok: bool = Schema(None, title="Database server is online")
    db_server_version: str = Schema(None, title="Version of the Database server")
    text_server_ok: bool = Schema(None, title="Text server is online")
    text_server_version: str = Schema(None, title="Version of the text server")
    opas_version: str = Schema(None, title="Version of OPAS")
    dataSource: str = Schema(None, title="Version of the API server software")
    timeStamp: str = Schema(None, title="Current time")
    serverContent: ServerStatusContent = Schema(None, title="Database Content (Counts)")
    # admin only
    user_count:  int = Schema(0, title="Number of users online")
    user_ip: str = Schema(None, title="Requestor's ip")
    config_name: str = Schema(None, title="Current Configuration Name")
    text_server_url: str = Schema(None, title="Current SOLR URL")
    cors_regex: str = Schema(None, title="Current CORS Regex")
    db_server_url: str = Schema(None, title="Current DB URL")

#-------------------------------------------------------

class JournalInfoListItem(BaseModel):    # Same as SourceInfoListItem minus a few fields
    sourceType: str = Schema(None, title="")
    PEPCode: str = Schema(None, title="")
    bannerURL: str = Schema(None, title="")
    displayTitle: str = Schema(None, title="Reference format for this source")
    srcTitle: str = Schema(None, title="Title of this source (from V1. Deprecated)")
    title: str = Schema(None, title="Title of this source")
    abbrev: str = Schema(None, title="")
    ISSN: str = Schema(None, title="")
    language: str = Schema(None, title="")
    yearFirst: str = Schema(None, title="")
    yearLast: str = Schema(None, title="")
    instanceCount: int = Schema(None, title="Number of document instances for this source")
    embargoYears: str = Schema(None, title="")
    
class JournalInfoStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[JournalInfoListItem] = []

class JournalInfoList(BaseModel):
    sourceInfo: JournalInfoStruct

#-------------------------------------------------------

class ReportListItem(BaseModel):
    row: dict = Schema({}, title="Fully flexible content report row from Database")
    
class ReportStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[ReportListItem] = []

class Report(BaseModel):
    report: ReportStruct
    
    #responseInfo: ResponseInfo
    #responseSet: List[VolumeListItem] = []   
    #reportTitle: str = Schema(None, title="")
    #reportData: List[ReportRow] = [] # ReportListStruct

#-------------------------------------------------------
# This is the model (SolrQuerySpec) 
# populated by parse_search_query_parameters from api parameter or body field requests
   
class SolrQuery(BaseModel):
    # Solr Query Parameters as generated by opasQueryHelper.parse_search_query_parameters
    searchQ: str = Schema(None, title="Query in Solr syntax", description="Advanced Query in Solr Q syntax (see schema names)")
    filterQ: str = Schema(None, title="Filter query in Solr syntax", description="Filter Query in Solr syntax (see schema names)")
    semanticDescription: str = Schema(None, title="Server's semantic description of the search")
    searchQPrefix: str = Schema("", title="Prefix to searchQ", description="Prefix to SearchQ, e.g., for Level 2")
    # returnFields: str = Schema(None, title="List of return fields", description="Comma separated list of return fields.  Default=All fields.")
    sort: str=Schema(None, title="Fields and direction by which to sort", description="arranges search results in either ascending (asc) or descending (desc) order. The parameter can be used with either numerical or alphabetical content. The directions can be entered in either all lowercase or all uppercase letters (i.e., both asc or ASC).")
    queryTermList: List[str] = None
    # extra fields
    likeThisID: str = Schema(None, title="DocumentID to use for reference to find documents like this.")
    analyzeThis: str = ""
    searchAnalysisTermList: List[str] = []

class SolrQueryOpts(BaseModel):
    # these all have proper defaults so technically, it can go into queries as is.
    qOper: str = Schema("AND", title="Implied Boolean connector", description="Implied Boolean connector between words in query")
    defType: QueryParserTypeEnum = Schema("lucene", title="Query parser to use, e.g., 'edismax'.  Default is 'standard' (lucene)")
    hl: str = Schema('true', title="Highlighting (KWIC)", description="Turns on highlighting if specified.")
    hlFields: str = Schema('text_xml', title="highlight fields (KWIC)", description="Specific fields to highlight.")
    hlMethod: str = Schema("unified", title="Highlighter method", description="Use either unified (fastest) or original.")
    hlFragsize: str = Schema(0, title="highlight fragment size", description="KWIC segment lengths")
    hlMaxAnalyzedChars: int = Schema(200, title="The character limit to look for highlights, after which no highlighting will be done. This is mostly only a performance concern")
    hlMaxKWICReturns: int = Schema(opasConfig.DEFAULT_MAX_KWIC_RETURNS, title="The character limit to look for highlights, after which no highlighting will be done. This is mostly only a performance concern")
    hlMultiterm: str = Schema('true', title="If set to true, Solr will highlight wildcard queries (and other MultiTermQuery subclasses). If false, they won’t be highlighted at all.")
    hlTagPost: str = Schema('@@@@#', title="Markup (tag) after hit term")
    hlTagPre: str = Schema('#@@@@', title="Markup (tag) before hit term")
    hlSnippets: str = Schema(None, title="Max KWIC Returns", description="Max number of highlights permitted per field")
    hlUsePhraseHighlighter: str = Schema('true', title="Solr will highlight phrase queries (and other advanced position-sensitive queries) accurately – as phrases. If false, the parts of the phrase will be highlighted everywhere instead of only when it forms the given phrase.")
    queryDebug: str = Schema("off", title="Turn Solr debug info 'on' or 'off' (default=off)")
    # facetFields: str = Schema(None, title="Faceting field list (comma separated list)", description="Returns faceting counts if specified.")

    # hlQ: str = Schema(None, title="Query to use for highlighting", description="allows you to highlight different terms than those being used to retrieve documents.")
    # maybe move these to a third part of SolrQuerySpec
    # moreLikeThis: bool = Schema(False, title="", description="If set to true, activates the MoreLikeThis component and enables Solr to return MoreLikeThis results.")
    moreLikeThisCount: int = Schema(0, title="MoreLikeThis count", description="Specifies the number of similar documents to be returned for each result. The default value is 5.")
    moreLikeThisFields: str = Schema(None, title="MoreLikeThis fields", description="Specifies the fields to use for similarity. If possible, these should have stored termVectors.")

# Will try a dict approach first, rather than this.
#class FacetSpec(BaseModel):
    #mincount: int = Schema(0, title="Minimum count for a facet to be included")
    #sort: str = Schema("count", title="Either 'count' (order by count) or 'index' (alphabetical)")
    #prefix: str = Schema(None, title="Limit terms to those starting with the prefix (if in the return set otherwise)")
    #contains: str = Schema(None, title="Limit terms to those containing the substring (if in the return set otherwise)")
    #excludeTerms: str = Schema(None, title="List of terms to exclude (comma separated list)")
    #facetRangesFields: str = Schema(None, title="Faceting Range field list (comma separated list)")
    #facetRangesStart: int = Schema(0, title="Minimum count for a facet to be included")
    #facetRangesEnd: int = Schema(0, title="Minimum count for a facet to be included")
    #limit: int = Schema(100, title="Facet Limit for Solr returns")
    #offset: int = Schema(0, title="Facet Offset in return set")
    
class SolrQuerySpec(BaseModel):
    label: str = Schema("default", title="User defined Label to save query spec")
    urlRequest: str = Schema(None, title="URL Request Made")
    # for PEP Opas, this is almost always pepwebdocs
    core: str = Schema("pepwebdocs", title="Selected core", description="Selected Solr core")
    fileClassification: str = Schema(None, title="File Status: free, current, archive, or offsite", description="File Status: free, current, archive, or offsite")
    fullReturn: bool = Schema(False, title="Request full length text return", description="Request full length text (XML) return (otherwise, return field length is capped)")
    abstractReturn: bool = Schema(False, title="Request return of abstracts or summaries", description="Request return of abstracts or summaries")
    returnFieldSet: str = Schema(None, title="Return field predefined set: DEFAULT, TOC, META, applies only to AdvancedSearch")
    returnFields: str = Schema(None, title="List of return fields (ExtendedSearch Only)", description="Comma separated list of return fields.  Only applies to ExtendedSearch.")
    returnFormat: str = Schema("HTML", title="Return type: XML, HTML, TEXT_ONLY", description="Return type applies to abstract and document fields only.")
    returnOptions: dict = Schema({}, title="Dictionary of special options for return data (e.g., glossary=False, ...)")
    limit: int = Schema(15, title="Record Limit for Solr returns")
    offset: int = Schema(0, title="Record Offset in return set")
    page: int = Schema(None, title="Page Number in return set")
    page_limit: int = Schema(None, title="Page Limit for Solr returns")
    page_offset: int = Schema(0, title="Page offset in return set")
    facetFields: str = Schema(None, title="Faceting field list (comma separated list)", description="Returns faceting counts if specified.")
    facetMinCount: int = Schema(1, title="Minimum count to return a facet")
    # TODO: facetRanges not yet implemented
    facetRanges: str = Schema(None, title="Faceting range list (comma separated list)", description="Returns faceting ranges if specified.")
    # facetSpec can include any Solr facet options, except any that are listed above.
    # option names should use _ instead of Solr's "."
    # unfortunately, because _ is period, you cannot use options with field names embedded, if they have an _,
    #   e.g., f.art_year_int_facet_range_start won't work to set the facet range start for art_year_int
    # You should be able to do this if the field doesn't have an underscore, though we don't have int
    #  fields like that currently.
    facetSpec: dict = Schema({}, title="Flexible Dictionary for facet specifications (using _ rather than .) Can include any Solr facet options, except any that are listed as fields above.")
    # sub structures
    solrQuery: SolrQuery = None
    solrQueryOpts: SolrQueryOpts = None

#-------------------------------------------------------
#  used to send individual components of the query, with individual options, to Opas (through API Body) 
#    which then processes it into a SolrQuery and sends to Solr.
class SolrQueryTermSub(BaseModel):
    connector: str = Schema(" && ", title="Boolean connector to prev term.  Must be && (default) or ||")
    field: str = Schema(None, title="Field to query")
    words: str = Schema(None, title="if string field: string or pattern to match; if text field: words, phrase with or without proximity qualifier, boolean connectors")
    parent: str = Schema(None, title="default parent to query or None")
    synonyms: bool = Schema(False, title="Request thesaurus expansion") # to turn on thesaurus match (appends syn) Default = False
    synonyms_suffix: str = Schema(opasConfig.SYNONYM_SUFFIX, title="suffix for field to use thesaurus; may not apply to all fields")

class SolrQueryTerm(BaseModel):
    connector: str = Schema(" && ", title="Boolean connector to prev term.  Must be && (default) or ||")
    subClause: List[SolrQueryTermSub] = Schema([], title="A sublist of query terms, to aggregate within parentheses; only connector is used with a SolrQueryTerm subclause")
    field: str = Schema(None, title="Field to query")
    words: str = Schema(None, title="if string field: string or pattern to match; if text field: words, phrase with or without proximity qualifier, boolean connectors")
    parent: str = Schema(None, title="default parent to query or None")
    synonyms: bool = Schema(False, title="Request thesaurus expansion") # to turn on thesaurus match (appends syn) Default = False
    synonyms_suffix: str = Schema(opasConfig.SYNONYM_SUFFIX, title="suffix for field to use thesaurus; may not apply to all fields")
    
class SolrQueryTermList(BaseModel):
    artLevel: int = Schema(None, title="1 for main document fields (e.g., text or title); 2 for child fields (e.g., para")
    qt: List[SolrQueryTerm] = []
    qf: List[SolrQueryTerm] = []
    solrQueryOpts: SolrQueryOpts = None
    # additions 2020-08-17 to make termlist a more complete solution for seaching
    similarCount: int = Schema(0, title=opasConfig.TITLE_SIMILARCOUNT)
    returnFields: str = Schema(None, title="List of return fields (ExtendedSearch Only)", description="Comma separated list of return fields.  Only applies to ExtendedSearch.")
    returnFormat: str = Schema("HTML", title="Return type: XML, HTML, TEXT_ONLY", description="Return type: XML, HTML, TEXT_ONLY")
    #fullReturn: bool = Schema(False, title="Request full length text return", description="Request full length text (XML) return (otherwise, return field length is capped)")
    abstractReturn: bool = Schema(False, title="Request return of abstracts or summaries", description="Request return of abstracts or summaries")
    facetFields: str = Schema(None, title="Faceting field list (comma separated list)", description="Returns faceting counts if specified.")
    facetMinCount: int = Schema(1, title="Minimum count to return a facet")
    # TODO: facetRanges not yet implemented
    facetRanges: str = Schema(None, title="Faceting range list (comma separated list)", description="Returns faceting ranges if specified.")
    # facetSpec can include any Solr facet options, except any that are listed above.
    # option names should use _ instead of Solr's "."
    facetSpec: dict = Schema({}, title="Flexible Dictionary for facet specifications (using _ rather than .) ")

#-------------------------------------------------------
# advanced Solr Raw return
class SolrReturnItem(BaseModel):
    solrRet: dict
        
class SolrReturnStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[SolrReturnItem] = []

class SolrReturnList(BaseModel):
    solrRetList: SolrReturnStruct

#-------------------------------------------------------
class SourceInfoListItem(BaseModel):    
    sourceType: str = Schema(None, title="")
    PEPCode: str = Schema(None, title="")
    bookCode: str = Schema(None, title="Like PEPCode (srcCode) but specialized for books where many books fall under the same src_code")
    documentID: str = Schema(None, title="OPAS ID for this document")
    bannerURL: str = Schema(None, title="Graphical banner/logo for this source (URL)")
    displayTitle: str = Schema(None, title="Reference format for this source")
    srcTitle: str = Schema(None, title="Title of this source (from V1. Deprecated)")
    title: str = Schema(None, title="Title of this source")
    authors: str = Schema(None, title="Authors of this source")
    pub_year: str = Schema(None, title="Year this was first published in the database")
    abbrev: str = Schema(None, title="Short form of the source, e.g., as used in references")
    ISSN: str = Schema(None, title="The ISSN for a journal or source that has an ISSN")
    ISBN10: str = Schema(None, title="The ISBN10 for a book, if available")
    ISBN13: str = Schema(None, title="The ISBN13 for a book, if available")
    language: str = Schema(None, title="Publication language (mainly)")
    yearFirst: str = Schema(None, title="First year available for this source")
    yearLast: str = Schema(None, title="Last year available for this source")
    instanceCount: int = Schema(None, title="Number of document instances for this source")
    embargoYears: str = Schema(None, title="")
    # these are not all currently used
    accessClassification: str = Schema(None, title="Document classification, e.g., Archive, Current, Free, OffSite")
    accessLimited: bool = Schema(True, title="Access is limited, preventing full-text return")
    accessLimitedReason: str = Schema(None, title="Explanation of user's access to this")
    accessLimitedDescription: str = Schema(None, title="Description of the access limitation applied")
    accessLimitedCurrentContent: bool = Schema(None, title="Access is limited by embargo to this specific content")
    accessLimitedPubLink: str = Schema(None, title="Link to the document or publisher in some cases where doc's not readable on PEP")
    

class SourceInfoStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[SourceInfoListItem] = []

class SourceInfoList(BaseModel):
    sourceInfo: SourceInfoStruct

#-------------------------------------------------------
class TermIndexItem(BaseModel):
    field: str = Schema(None, title="The field where the term indexed was checked.")
    term: str = Schema(None, title="The term as indexed by the system.")
    termCount: int = Schema(None, title="The number of documents with this term.")
    
class TermIndexStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[TermIndexItem] = []

class TermIndex(BaseModel):
    termIndex: TermIndexStruct

#-------------------------------------------------------
class VideoInfoListItem(BaseModel):    # Same as SourceInfoListItem minus a few fields
    sourceType: str = Schema(None, title="")
    PEPCode: str = Schema(None, title="")
    bannerURL: str = Schema(None, title="")
    displayTitle: str = Schema(None, title="Reference format for this source")
    title: str = Schema(None, title="Title of this source")
    abbrev: str = Schema(None, title="")
    ISSN: str = Schema(None, title="")
    language: str = Schema(None, title="")
    yearFirst: str = Schema(None, title="")
    yearLast: str = Schema(None, title="")
    instanceCount: int = Schema(None, title="Number of document instances for this source")
    embargoYears: str = Schema(None, title="")
    # these are not all currently used
    accessClassification: str = Schema(None, title="Document classification, e.g., Archive, Current, Free, OffSite")
    accessLimited: bool = Schema(True, title="Access is limited, preventing full-text return")
    accessLimitedReason: str = Schema(None, title="Explanation of user's access to this")
    accessLimitedDescription: str = Schema(None, title="Description of the access limitation applied")
    accessLimitedCurrentContent: bool = Schema(None, title="Access is limited by embargo to this specific content")
    accessLimitedPubLink: str = Schema(None, title="Link to the document or publisher in some cases where doc's not readable on PEP")

class VideoInfoStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[VideoInfoListItem] = []

class VideoInfoList(BaseModel):
    sourceInfo: VideoInfoStruct

#-------------------------------------------------------
class VolumeListItem(BaseModel):
    PEPCode: str = Schema(None, title="")
    vol: str = Schema(None, title="")
    year: str = Schema(None, title="")
    years: list = Schema([], title="")
    count: int = Schema(0, title="")
    
#-------------------------------------------------------

class VolumeListStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[VolumeListItem] = []   

class VolumeList(BaseModel):
    volumeList: VolumeListStruct
    
#-------------------------------------------------------
class WhatsNewListItem(BaseModel):
    displayTitle: str = Schema(None, title="")
    abbrev: str = Schema(None, title="")
    volume: str = Schema(None, title="")
    issue: str = Schema(None, title="")
    year: str = Schema(None, title="")
    PEPCode: str = Schema(None, title="")
    srcTitle: str = Schema(None, title="")
    updated: str = Schema(None, title="")
    volumeURL: str = Schema(None, title="")

class WhatsNewListStruct(BaseModel):
    responseInfo: ResponseInfo
    responseSet: List[WhatsNewListItem] = []   

class WhatsNewList(BaseModel):
    whatsNew: WhatsNewListStruct

    
#-------------------------------------------------------
# Perhaps use termindex instead
#class WordIndexItem(BaseModel):
    #word: str = Schema(None, title="Word indexed by the system.")
    #wordCount: int = Schema(None, title="The number of times the word was found.")
    
#class WordIndexStruct(BaseModel):
    #responseInfo: ResponseInfo
    #responseSet: List[WordIndexItem] = []

#class WordIndex(BaseModel):
    #wordIndex: WordIndexStruct
    
if __name__ == "__main__":
    pass

