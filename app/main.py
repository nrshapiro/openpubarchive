#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__      = "Neil R. Shapiro"
__copyright__   = "Copyright 2020, Psychoanalytic Electronic Publishing"
__license__     = "Apache 2.0"
__version__     = "2020.1213.2.Alpha"
__status__      = "Development"

"""
Main entry module for PEP version of OPAS API

This API server is based on the existing PEP-Web API 1.0.  The data returned 
may have additional fields but should be otherwise compatible with PEP API clients
such as PEP-Easy.

It's an initial version of the Opas Solr Server (API); it's not yet "generic", it's
schema and functionality dependent on PEP's needs (who is funding development).  But
it would be a start, that could be genericized for a general purpose OPAS.

To Install (at least in windows)
  rem python 3.7 required
  python -m venv .\venv
  .\venv\Scripts\activate.bat
  pip install --trusted-host pypi.python.org -r /app/requirements.txt
  rem if it complains pip is not up to date
  python -m pip install --upgrade pip

Run with:
    uvicorn server:app --reload

    or for debug:

    uvicorn main:app --debug --log-level=debug

(Debug set up in this file as well: app = FastAPI(debug=True))

Endpoint and model documentation automatically available when server is running at:

  http://subdomain.domain:port/docs
  (components above as needed)

  (base URL + "/docs")
  e.g.,
  http://api.pep-web.rocks/docs
  http://api.pep-web.org/docs
  http://localhost:8000/docs
  etc.

"""
#----------------------------------------------------------------------------------------------
# Coding Standards
#----------------------------------------------------------------------------------------------
# Original code came from camelCase, my previously main code standard.  However, to make
# it at least a bit more acceptible to modern Pythonistas, I've converted variables and
# functions to snake_case.  There is still a mix, which does serve a purpose of separating
# names by use.

#Naming standards: 
    #- converted variables (still may be some camelCase) in snake_case
    #- class names in upper camelCase per python standards
    #- model attributes - lower camelCase
    #- database fields/attributes - snake_case
    #- solr attributes - snake_case
    #- api path parameters - upper CamelCase
    #- api query parameters - all lowercase (unseparated)

#----------------------------------------------------------------------------------------------
# Revisions (Changelog) 
#----------------------------------------------------------------------------------------------
# See https://github.com/Psychoanalytic-Electronic-Publishing/OpenPubArchive-Content-Server/wiki/CHANGELOG.md

# --------------------------------------------------------------------------------------------
# IMPORTANT TODOs (List)
# --------------------------------------------------------------------------------------------
# - Fix abstract return - Leadin needs to be inside HTML tagging (though works fine for display right now)
# - Think about what to do when a Solr query is in error, and solr dumps back.
# - Finish transition to PySolr...extended query (and perhaps another endpoint) still uses solrpy

# --------------------------------------------------------------------------------------------
# Not necessarily in the server code, but General TODOs
# --------------------------------------------------------------------------------------------
# - Add in detail for putciteashere gen from pepkbd3-abstract-html.xslt
#
#----------------------------------------------------------------------------------------------

import sys
sys.path.append('./config')
sys.path.append('./libs')
sys.path.append('./libs/solrpy')

import os.path
import time
import datetime
from datetime import datetime
import re
# import secrets
import wget
import shlex
import io
import pathlib
import urllib.parse
import inspect

# import json

from urllib import parse

import uvicorn
from fastapi import FastAPI, Query, Body, Path, Header, Security, Depends, HTTPException, File, Form #, UploadFile, Cookie
from fastapi.openapi.utils import get_openapi
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.security.api_key import APIKeyQuery, APIKeyCookie, APIKeyHeader, APIKey
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, FileResponse, StreamingResponse # RedirectResponse
from starlette.middleware.cors import CORSMiddleware
import starlette.status as httpCodes
#from starlette.middleware.sessions import SessionMiddleware
#from typing import Optional
import pandas as pd

import requests
from requests.auth import HTTPBasicAuth
# import aiofiles
# from typing import List

TIME_FORMAT_STR = '%Y-%m-%dT%H:%M:%SZ'

from pydantic import ValidationError
import solrpy as solr # needed for extended search
from config.opasConfig import OPASSESSIONID, OPASACCESSTOKEN, OPASEXPIRES
import config.opasConfig as opasConfig
import logging
logger = logging.getLogger(__name__)

# import jwt
import localsecrets
import libs.opasAPISupportLib as opasAPISupportLib
from configLib.opasCoreConfig import EXTENDED_CORES, SOLR_DOCS

from errorMessages import *
import models
import opasCentralDBLib
import opasFileSupport
import opasQueryHelper
import opasSchemaHelper
import opasDocPermissions
import opasPySolrLib
from opasPySolrLib import search_text, search_text_qs

# Check text server version
text_server_ver = None
text_server_url = localsecrets.SOLRURL
PARAMS = {'wt':'json'}
url = f"{localsecrets.SOLRURL}admin/info/system"
if localsecrets.SOLRUSER is not None:
    # need username and password
    r = requests.get(url = url, params = PARAMS, auth=HTTPBasicAuth(localsecrets.SOLRUSER, localsecrets.SOLRPW))
else:
    r = requests.get(url = url, params = PARAMS)

if r.status_code == 200:
    ver_json = r.json()
    try:
        text_server_ver = ver_json["lucene"]["lucene-spec-version"]
    except KeyError:
        text_server_ver = ver_json["lucene"]["solr-spec-version"]

# to protect documentation, use: app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
#app = FastAPI()

app = FastAPI(
    debug=False,
    title="OpenPubArchive Server (OPAS) API for PEP-Web",
    description = "Open Publications Archive Server API for PEP-Web by Psychoanalytic Electronic Publishing (PEP)",
        version = f"{__version__}",
        static_directory=r"./docs",
        swagger_static={
            "favicon": "pepfavicon"
            },
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex = localsecrets.CORS_REGEX, 
    allow_origins = localsecrets.CORS_ORIGINS, 
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers = ["*"],
)

msg = 'Started at %s' % datetime.today().strftime('%Y-%m-%d %H:%M:%S"')
logger.info(msg)

# ############################################################################
# Dependence routines
# ############################################################################
def get_client_id(response: Response,
                  request: Request,
                  client_id: int=Header(0, title=opasConfig.TITLE_CLIENT_ID,
                                           description=opasConfig.DESCRIPTION_CLIENT_ID)
                  ):
    """
    Dependency for client id: see find_client_id
    """
    ret_val = opasDocPermissions.find_client_id(request, response)
    return ret_val

def get_client_session(response: Response,
                       request: Request,
                       client_session: str=Header(None, title=opasConfig.TITLE_CLIENT_ID, description=opasConfig.DESCRIPTION_CLIENT_SESSION), 
                       client_id: int=Depends(get_client_id), 
                       ):
    """
    Dependency for client_session id:
           gets it from header;
           if not there, gets it from query param;
           if not there, gets it from a cookie
           
    Call routine in library so other routines can get resolve from there as well       
    """
    if client_session == 'None': # Not sure where this is coming from as string, but fix it.
        client_session = None
        
    if client_id is None or client_id == 0 or client_id == opasConfig.NO_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Must have a valid client-id")
    
    session_id = opasDocPermissions.find_client_session_id(request, response, client_session)
    # client_id = get_client_id(response, request, 0)
    # if there's no client session, get a session_id from PaDS without logging in
    if session_id is None:
        # get one from PaDS, without login info
        # session_info, pads_session_info = opasDocPermissions.pads_get_session(client_id=client_id)
        logger.info(f"Client {client_id} request w/o sessionID: {request.url._url}'")
        logger.info(f"get_client_session (no session) called by {inspect.stack()[1].function}")
        session_info = opasDocPermissions.get_authserver_session_info(session_id=session_id, client_id=client_id)
        try:
            session_id = session_info.session_id
        except Exception as e:
            # We didn't get a session id
            msg = f"Session ID not received from authserver for client id {client_id} and session {client_session}.  Raising Exception 424 ({e})."
            logger.error(msg)
            raise HTTPException(
                status_code=httpCodes.HTTP_424_FAILED_DEPENDENCY,
                detail=ERR_MSG_PASSWORD + f" ({e})", 
            )
        else:
            if session_id is not None:
                opasAPISupportLib.save_opas_session_cookie(request, response, session_id)
            else:
                logger.info("Session_id is None, no cookie saved.")

    if session_id is None or len(session_id) < 12:
        msg = f"Session ID not resolved {session_id}.  Raising Exception 424."
        logger.error(msg)
        raise HTTPException(
            status_code=httpCodes.HTTP_424_FAILED_DEPENDENCY,
            detail=ERR_MSG_PASSWORD + f" {msg}", 
        )
        
    return session_id       
    
security = HTTPBasic()
def login_via_pads(request: Request,
                   response: Response, 
                   credentials: HTTPBasicCredentials = Depends(security)):

    client_id = opasDocPermissions.find_client_id(request, response)
    # ocd = opasCentralDBLib.opasCentralDB()
    session_id = opasDocPermissions.find_client_session_id(request, response)
    # Ok, login
    pads_session_info = opasDocPermissions.authserver_login(username=credentials.username,
                                                      password=credentials.password,
                                                      session_id=session_id,
                                                      client_id=client_id)
  
    if pads_session_info is None or pads_session_info.IsValidLogon == False:
        raise HTTPException(
            status_code=httpCodes.HTTP_401_UNAUTHORIZED,
            detail=ERR_MSG_PASSWORD, 
            headers={"WWW-Authenticate": "Basic"},
        )
    else:
        session_info = opasDocPermissions.get_authserver_session_info(pads_session_info.SessionId, client_id, pads_session_info=pads_session_info)
        # Confirm that the request-response cycle completed successfully.
        ret_val = session_info
    
    return ret_val

#-----------------------------------------------------------------------------
api_key_query = APIKeyQuery(name=localsecrets.API_KEY_NAME, auto_error=False)
api_key_header = APIKeyHeader(name=localsecrets.API_KEY_NAME, auto_error=False)
api_key_cookie = APIKeyCookie(name=localsecrets.API_KEY_NAME, auto_error=False)
#-----------------------------------------------------------------------------
async def get_api_key(api_key_query: str = Security(api_key_query),
                      api_key_header: str = Security(api_key_header),
                      api_key_cookie: str = Security(api_key_cookie),
                      ):

    if api_key_query == localsecrets.API_KEY:
        return api_key_query
    elif api_key_header == localsecrets.API_KEY:
        return api_key_header
    elif api_key_cookie == localsecrets.API_KEY:
        return api_key_cookie
    else:
        raise HTTPException(
            status_code=httpCodes.HTTP_403_FORBIDDEN,
            detail=ERR_CREDENTIALS
        )

# ############################################################################
# End Dependence routines
# ############################################################################

def log_endpoint(request, client_id=None, session_id=None, path_params=True):
    if client_id == 3: # PaDS, sends a lot of requests at once, so mute
        logger.debug(f"***[{client_id}:{session_id}]:{request['path']}***")
        #logger.info(urllib.parse.unquote(f"....{request.url}"))
    else:
        logger.info(f"*************[{client_id}:{session_id}]:{request['path']}********************************************************************************")
        url = urllib.parse.unquote(f"....{request.url}")
        logger.info(f"************ URL: {url}")

def log_endpoint_time(request, ts): 
    if opasConfig.LOG_CALL_TIMING:
        logger.info(f"***{request['path']} response time: {time.time() - ts}***")

# ############################################################################
# EndPoints
# ############################################################################
#-----------------------------------------------------------------------------
@app.get("/v2/Api/OpenapiSpec", tags=["API documentation"], summary=opasConfig.ENDPOINT_SUMMARY_OPEN_API)
async def api_openapi_spec(api_key: APIKey = Depends(get_api_key), 
                           ):
    """
    This returns openapi documentation in json that can be loaded to Swagger

    Requires API key.

    """
    #Also a good demo of the simplicity to add APIKey to any endpoint. The APIKey
    #can be added to the header (see postman example), in the interactive documentation
    #it's just a matter of pressing the lock icon and filling out the form.  It can also
    #be supplied as a query parameter in the endpoint call.

    response = JSONResponse(get_openapi(title="FastAPI", version=1, routes=app.routes))
    return response

#-----------------------------------------------------------------------------
@app.get("/v2/Admin/LogLevel/", tags=["Admin"], summary="Admin function to change logging level")
async def admin_set_loglevel(response: Response, 
                             request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                             api_key: APIKey = Depends(get_api_key), 
                             client_id:int=Depends(get_client_id),
                             level:str=Query("WARNING", title="Log Level", description="DEBUG, INFO, WARNING, or ERROR"),
                            ): 
    # TODO: Make this an admin only function
    try:
        # not necessary, since setLevel accepts the same strings
        # but this protects from name input errors
        # (as does the Exception)
        # At this point there's no reason I see to accept numeric levels
        level = level.upper()
        if level == "DEBUG":
            lev_int = logging.DEBUG
        elif level == "INFO":
            lev_int = logging.INFO
        elif level == "WARNING" or level == "WARN":
            lev_int = logging.WARNING
        elif level == "ERROR":
            lev_int = logging.ERROR
        
        logger = logging.getLogger() # Get root logger
        logger.setLevel(lev_int)
    except Exception as e:
        logger.error(f"Error setting log level {e}.  Current level {logger.level}")
    
    levels = {10: "DEBUG", 20: "INFO", 30: "WARNING", 40: "ERROR", 50: "CRITICAL"}
    ret_val = levels.get(logger.level, str(logger.level))
    return ret_val
#-----------------------------------------------------------------------------
@app.get("/v2/Api/LiveDoc", tags=["API documentation"], summary=opasConfig.ENDPOINT_SUMMARY_DOCUMENTATION)
async def api_live_doc(api_key: APIKey = Depends(get_api_key),
                       ):
    """
    This returns an HTML page of interactive api documentation.

    Requires API key.

    """
    #It's really only useful if/when we turn off the free documentation
    #changing the app call to:

        #app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    response = get_swagger_ui_html(openapi_url="/v2/Api/OpenapiSpec", title="docs")

    #TODO: should we set this wherever the key is required?
    response.set_cookie(
        localsecrets.API_KEY_NAME,
        value=api_key,
        domain=localsecrets.COOKIE_DOMAIN,
        httponly=True,
        max_age=1800,
        expires=1800,
    )
    return response

#-----------------------------------------------------------------------------
@app.get("/v2/Api/Status/", response_model=models.APIStatusItem, response_model_exclude_unset=True, tags=["API documentation"], summary=opasConfig.ENDPOINT_SUMMARY_API_STATUS)
async def api_status(response: Response, 
                     request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                    ):
    """
    ## Function
       <b>Return the status of the API to check if it's available.</b>

    ## Return Type
       models.ServerStatusItem

    ## Status
       Status: Working

    ## Sample Call
         /v2/Api/Status/

    """
    try:
        api_status_item = models.APIStatusItem(timeStamp = datetime.utcfromtimestamp(time.time()).strftime('%Y-%m-%dT%H:%M:%SZ'), 
                                               opas_version = __version__, 
                                              )

    except ValidationError as e:
        logger.warning("ValidationError", e.json())
        raise HTTPException(
            status_code=httpCodes.HTTP_400_BAD_REQUEST,
            detail=ERR_MSG_STATUS_DATA_ISSUE
        )

    return api_status_item

#-----------------------------------------------------------------------------
@app.get("/v2/Reports/{report}", response_model=models.Report, tags=["Reports"], summary=opasConfig.ENDPOINT_SUMMARY_REPORTS)
async def reports(response: Response, 
                  request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                  report: models.ReportTypeEnum=Path(..., title="Report Requested", description="One of the predefined report names"),
                  sessionid: str=Query(None, title="SessionID", description="Filter by this Session ID"),
                  userid:str=Query(None, title="Global User ID", description="Filter by this common (global) system userid"), 
                  startdate: str=Query(None, title=opasConfig.TITLE_STARTDATE, description=opasConfig.DESCRIPTION_STARTDATE), 
                  enddate: str=Query(None, title=opasConfig.TITLE_ENDDATE, description=opasConfig.DESCRIPTION_ENDDATE),
                  matchstr: str=Query(None, title=opasConfig.TITLE_REPORT_MATCHSTR, description=opasConfig.DESCRIPTION_REPORT_MATCHSTR), 
                  limit: int=Query(100, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                  offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                  download:bool=Query(False, title=opasConfig.TITLE_DOWNLOAD, description=opasConfig.DESCRIPTION_DOWNLOAD), 
                  client_id:int=Depends(get_client_id), 
                  client_session:str= Depends(get_client_session), 
                  api_key: APIKey = Depends(get_api_key)
                  ):
    """
    ### Function
      <b>Returns a report in JSON per the Reports</b>

      Requires API key.
      
    ### Return Type

      models.Report

    ### Status
       In Development

    ### Sample Call
         #/v2/Reports/

    ### Notes
      For session-views and user-searches reports:
         matchstr does a regex search of the url (endpoint plus parameters)
         e.g.,
           /Documents/Document/AIM.023.0227A/
         
      For document-view-log
         matchstr does a regex search of the document type, e.g.,
            PDF
 
      Note as the examples above, you don't need to include special regex wildcards (it matches anywhere in the text)

    ### Potential Errors
       #NA


    """
    opasDocPermissions.verify_header(request, "Reports") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    userid_condition = ""
    sessionid_condition = ""
    extra_condition = ""
    #username_condition = ""
    standard_filter = "1"
    limited_count = 0
    ret_val = None

    if sessionid is not None:
        sessionid_condition = f" AND session_id={sessionid}"

    # this user id will be whatever I get from the authentication system, not the numeric userid I have
    if userid is not None:
        userid_condition = f" AND global_uid={userid}"

    try:
        if enddate is not None:
            enddate = enddate.replace("-", "")

        if startdate is not None:
            startdate = startdate.replace("-", "")

    except Exception as e:
        logger.warning(f"Bad start or end date specified to reports {e}")


    if startdate is not None:
        if enddate is not None:
            date_condition = f" AND last_update BETWEEN {startdate} AND {enddate}"
        else:
            date_condition = f" AND last_update >= {startdate}"
    else:
        if enddate is not None:
            date_condition = f" AND last_update <= {enddate}"
        else:
            date_condition = ""

    limit_clause = ""
    if limit is not None:
        limit_clause = f"LIMIT {limit}"
        if offset != 0:
            limit_clause += f" OFFSET {offset}"
    else:
        limit = 0 # (None) for ResponseInfo since it has to be an integer

    report_view = None
    header = None
    if report == models.ReportTypeEnum.documentViewLog:
        standard_filter = "1 = 1 " 
        if matchstr is not None:
            extra_condition = f" AND type RLIKE '{matchstr}'"
        report_view = "vw_reports_document_activity"
        orderby_clause = "ORDER BY last_update DESC"
        header = ["user id",
                  "session id",
                  "document id",
                  "view type",
                  "last update"]
        
    elif report == models.ReportTypeEnum.sessionLog:
        standard_filter = "1 = 1 " 
        report_view = "vw_reports_session_activity"
        if matchstr is not None:
            extra_condition = f" AND params RLIKE '{matchstr}'"
        orderby_clause = "ORDER BY last_update DESC"
        header = ["user id",
                  "session id",
                  "session_start",
                  "session end",
                  "item of interest",
                  "endpoint",
                  "params",
                  "status code",
                  "status message",
                  "last update"]
    elif report == models.ReportTypeEnum.userSearches:
        standard_filter = "endpoint rlike '.*Search' "
        if matchstr is not None:
            extra_condition = f" AND params RLIKE '{matchstr}'"
        report_view = "vw_reports_user_searches"
        orderby_clause = "ORDER BY last_update DESC"
        header = ["user id", 
                  "session id",
                  "session start",
                  "item of interest",
                  "endpoint",
                  "params",
                  "status code",
                  "status message",
                  "last update"]
    elif report == models.ReportTypeEnum.documentViews:
        standard_filter = "1 = 1 " 
        report_view = "vw_reports_document_views"
        orderby_clause = "ORDER BY views DESC"
        header = ["document id",
                  "view type",
                  "view count"]
    else:
        report_view = None

    if report_view is None:
        raise HTTPException(
            status_code=httpCodes.HTTP_404_NOT_FOUND, 
            detail=ERR_MSG_REPORT_NOT_FOUND
        )        

    # Get report
    select = f"""SELECT * from {report_view}
                 WHERE {standard_filter}
                 {date_condition}
                 {userid_condition}
                 {sessionid_condition}
                 {extra_condition}
                 {orderby_clause}
                 """

    count = ocd.get_select_count(select)
    if count == 0:
        raise HTTPException(
            status_code=httpCodes.HTTP_404_NOT_FOUND, 
            detail=ERR_MSG_NO_DATA_FOR_REPORT
        )               
    else:
        # now add the limit clause
        select += f"{limit_clause};"
        
        if download:
            # Download CSV of selected set.  Returns only response with download, not usual documentList
            #   response to client
            results = ocd.get_select_as_list(select)
            df = pd.DataFrame(results)
            stream = io.StringIO()
            df.to_csv(stream, header=header, index = False)
            response = StreamingResponse(iter([stream.getvalue()]),
                                         media_type="text/csv"
                                               )
            response.headers["Content-Disposition"] = f"attachment; filename={report_view}.csv"
            ret_val = response
        else:
            results = ocd.get_select_as_list_of_dicts(select)
            limited_count = len(results)

            response_info = models.ResponseInfo(count = limited_count,
                                                fullCount = count,
                                                totalMatchCount = count,
                                                limit = limit,
                                                offset = offset,
                                                listType="reportlist",
                                                fullCountComplete = limited_count >= count,
                                                request=f"{request.url._url}",
                                                timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                                )   

            if count == 0:
                raise HTTPException(
                    status_code=httpCodes.HTTP_404_NOT_FOUND, 
                    detail=ERR_MSG_NO_DATA_FOR_REPORT
                )       

            report_struct = models.ReportStruct( responseInfo = response_info, 
                                                 responseSet = results
                                                 )

            ret_val = models.Report(report = report_struct)

    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_REPORTS,
                                api_endpoint_method=opasCentralDBLib.API_ENDPOINT_METHOD_GET,
                                item_of_interest=report, 
                                session_info=session_info, 
                                params=request.url._url,
                                return_status_code = response.status_code,
                                status_message=opasCentralDBLib.API_STATUS_SUCCESS
                                )

    #  return it.
    return ret_val

#-----------------------------------------------------------------------------
@app.post("/v2/Client/Configuration/", response_model=models.ClientConfig, response_model_exclude_unset=True, tags=["Client"], summary=opasConfig.ENDPOINT_SUMMARY_SAVE_CONFIGURATION, status_code=201)
async def client_save_configuration(response: Response, 
                                    request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                                    configuration:models.ClientConfig=Body(None, embed=False, title=opasConfig.TITLE_ADMINCONFIG, decription=opasConfig.DESCRIPTION_ADMINCONFIG), # allows full specification
                                    client_id:int=Depends(get_client_id), 
                                    client_session:str= Depends(get_client_session), 
                                    api_key: APIKey = Depends(get_api_key)
                                    ):

    """
    ## Function
       <b>Save global configuration settings for the client.  If the configname already exists for that client app,
           an error 409 is returned.</b>

       Client-specific Administrative function to store the global settings for the client app.  A client can store multiple settings under different names.      

       Requires API key and client_id in the header (use 'client-id' in call header).

       TODO: Consider whether to require logging in as an admin to use this feature.
        (first need to consider whether the app would also be logged into the central auth (e.g., PaDS)
        is made, since the only admin login is local login!)


    ## Return Type
       models.ClientConfig

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Client/Configuration/

    ## Notes
         NA

    ## Potential Errors
       NA

    """
    #  api_key needs to be supplied, e.g., in the header
    #  set database for confg, overwriting previous

    #  return current config (old if it fails).

    opasDocPermissions.verify_header(request, "ClientSaveConfig") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    # ensure user is admin
    ret_val = None

    #if 1: # for now, just use API_KEY as the requirement.  Later admin?  if ocd.verify_admin(session_info):
    ret_val, msg = ocd.save_client_config(session_id=client_session,
                                          client_id=client_id, 
                                          client_configuration=configuration,
                                          replace=False)
    status_code = ret_val
    if status_code not in (200, 201):
        raise HTTPException(
            status_code=status_code, 
            detail=msg
        )
    else:
        ret_val = configuration
        
    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_CLIENT_CONFIGURATION,
                                api_endpoint_method=opasCentralDBLib.API_ENDPOINT_METHOD_POST, 
                                session_info=session_info, 
                                params=request.url._url,
                                status_message=opasCentralDBLib.API_STATUS_SUCCESS, 
                                return_status_code = status_code
                                )
    return ret_val

#-----------------------------------------------------------------------------
@app.put("/v2/Client/Configuration/", response_model=models.ClientConfig, response_model_exclude_unset=True, tags=["Client"], summary=opasConfig.ENDPOINT_SUMMARY_SAVEORREPLACE_CONFIGURATION, status_code=201)
async def client_update_configuration(response: Response, 
                                      request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                                      configuration:models.ClientConfig=Body(None, embed=False, title=opasConfig.TITLE_ADMINCONFIG, decription=opasConfig.DESCRIPTION_ADMINCONFIG), # allows full specification
                                      client_id:int=Depends(get_client_id), 
                                      client_session:str= Depends(get_client_session), 
                                      api_key: APIKey = Depends(get_api_key)
                                      ):

    """
    ## Function
       <b>Update global configuration settings for the client.  If the configname already exists
          for that client app, the previous settings are overwritten.</b>

       Client-specific Administrative function to store the global settings for the client app.
       A client can store multiple settings under different names.      

       Requires API key and client_id in the header (use 'client-id' in call header).

       TODO: Consider whether to require logging in as an admin to use this feature.
        (first need to consider whether the app would also be logged into the central auth (e.g., PaDS)
        is made, since the only admin login is local login!)


    ## Return Type
       models.ClientConfig

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Client/Configuration/

    ## Notes
         NA

    ## Potential Errors
       NA

    """
    #  api_key needs to be supplied, e.g., in the header
    #  set database for confg, overwriting previous
    #  return current config (old if it fails).

    opasDocPermissions.verify_header(request, "ClientUpdateConfig") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    # ensure user is admin
    ret_val = None

    #if 1: # for now, just use API_KEY as the requirement.  Later admin?  if ocd.verify_admin(session_info):
    try:
        status_code, msg = ocd.save_client_config(session_id=session_info.session_id,
                                                  client_id=client_id, 
                                                  client_configuration=configuration,
                                                  replace=True)
    except Exception as e:
        logger.error(f"Trapped error saving client config: {e}")

    if status_code not in (200, 201):
        logger.error(f"HTTPException Called: {status_code}")
        raise HTTPException(
            status_code=status_code, # HTTP_xxx
            detail=msg
        )
    else:
        ret_val = configuration

    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_CLIENT_CONFIGURATION,
                                api_endpoint_method=opasCentralDBLib.API_ENDPOINT_METHOD_PUT, 
                                session_info=session_info, 
                                params=request.url._url,
                                status_message=opasCentralDBLib.API_STATUS_SUCCESS, 
                                return_status_code = status_code
                                )
    return ret_val

#-----------------------------------------------------------------------------
@app.get("/v2/Client/Configuration/", response_model=models.ClientConfig, response_model_exclude_unset=True, tags=["Client"], summary=opasConfig.ENDPOINT_SUMMARY_GET_CONFIGURATION)
async def client_get_configuration(response: Response, 
                                   request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                                   configname:str=Query(..., title=opasConfig.TITLE_ADMINCONFIGNAME, description=opasConfig.DESCRIPTION_ADMINCONFIGNAME, min_length=4),
                                   api_key: APIKey = Depends(get_api_key), 
                                   client_id:int=Depends(get_client_id), 
                                   client_session:str= Depends(get_client_session)
                                   ): 

    """
    ## Function
       <b>Return saved configuration settings for the client_id (use 'client-id' in call header)</b>

       Client-specific Administrative function to store the global settings for the client app.
       A client can store multiple settings under different names.

       Requires API key and client_id in the header (use 'client-id' in call header).

       TODO: Consider whether to require logging in as an admin to use this feature.
        (first need to consider whether the app would also be logged into the central auth (e.g., PaDS)
        is made, since the only admin login is local login!)

    ## Return Type
       models.ClientConfig

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Client/Configuration/?configname="pepweb2021"

    ## Notes
         NA

    ## Potential Errors
       NA

    """
    
    opasDocPermissions.verify_header(request, "ClientGetConfig") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    # for now, just use API_KEY as the requirement.  Later admin?  
    ret_val = ocd.get_client_config(client_id=client_id,
                                    client_config_name=configname)


    if ret_val is None:
        status_code = httpCodes.HTTP_404_NOT_FOUND
        raise HTTPException(
            status_code=httpCodes.HTTP_404_NOT_FOUND, 
            detail=ERR_MSG_CONFIG_NOT_FOUND
        )
    else:
        status_code = httpCodes.HTTP_200_OK

    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_CLIENT_CONFIGURATION,
                                api_endpoint_method=opasCentralDBLib.API_ENDPOINT_METHOD_GET, 
                                session_info=session_info, 
                                params=request.url._url,
                                status_message=opasCentralDBLib.API_STATUS_SUCCESS, 
                                return_status_code = status_code
                                )

    #  return it.
    return ret_val

#-----------------------------------------------------------------------------
@app.delete("/v2/Client/Configuration/", response_model=models.ClientConfig, response_model_exclude_unset=True, tags=["Client"], summary=opasConfig.ENDPOINT_SUMMARY_DELETE_CONFIGURATION, status_code=200)
async def client_del_configuration(response: Response, 
                                   request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                                   configname:str=Query(..., title=opasConfig.TITLE_ADMINCONFIGNAME, description=opasConfig.DESCRIPTION_ADMINCONFIGNAME, min_length=4),
                                   client_id:int=Depends(get_client_id), 
                                   client_session:str= Depends(get_client_session), 
                                   api_key: APIKey = Depends(get_api_key)
                                   ): 

    """
    ## Function
       <b>Delete a specific configuration set (settings) for the specific client_id</b>

       Requires API key and client_id in the header (use 'client-id' in call header).
       clientID should also be in the configuration body parameter (as a good practice).

    ## Return Type
       models.ClientConfig

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Client/Configuration/?configname="pepweb2021"

    ## Notes
         NA

    ## Potential Errors
       NA

    """
    
    opasDocPermissions.verify_header(request, "ClientDelConfig") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    #for now, just use API_KEY as the requirement.  Later admin?
    ret_val = ocd.del_client_config(client_id=client_id,
                                    client_config_name=configname)

    if ret_val is None:
        raise HTTPException(
            status_code=httpCodes.HTTP_404_NOT_FOUND, 
            detail=f"Configname {configname} Not found"
        )        

    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_CLIENT_CONFIGURATION,
                                api_endpoint_method=opasCentralDBLib.API_ENDPOINT_METHOD_DELETE, 
                                session_info=session_info, 
                                params=request.url._url,
                                status_message=opasCentralDBLib.API_STATUS_SUCCESS
                                )
    #  return it.
    return ret_val

#-----------------------------------------------------------------------------
@app.get("/v2/Session/WhoAmI/", response_model=models.SessionInfo, response_model_exclude_unset=True, tags=["Session"], summary=opasConfig.ENDPOINT_SUMMARY_WHO_AM_I)
async def session_whoami(response: Response,
                         request: Request,
                         client_id:int=Depends(get_client_id), 
                         client_session:str= Depends(get_client_session)
                         ):
    """
    ## Function
       <b>Temporary endpoint for debugging purposes</b>

       This is only a stopgap for development
       All authentication processing is to be done in PaDS as planned
       (though it may be this stays conditionally for future iteration of local development TBD)


    ## Return Type
       models.SessionInfo

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Session/WhoAmI/

    ## Notes
       NA

    ## Potential Errors
       NA

    """
    opasDocPermissions.verify_header(request, "WhoAmI") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    if client_session is not None:
        ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)
    else:
        logger.error(f"Bad Request: Client-Session ID not provided")
        raise HTTPException(
            status_code=httpCodes.HTTP_400_BAD_REQUEST,
            detail=ERR_MSG_SESSION_ID_ERROR
        )
        
    return(session_info)

#-----------------------------------------------------------------------------
@app.get("/v2/Session/Status/", response_model=models.ServerStatusItem, response_model_exclude_unset=True, tags=["Session"], summary=opasConfig.ENDPOINT_SUMMARY_SERVER_STATUS)
async def session_status(response: Response, 
                         request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                         moreinfo: bool=Query(False, title=opasConfig.TITLE_MOREINFO, description=opasConfig.DESCRIPTION_MOREINFO),
                         client_id:int=Depends(get_client_id), 
                         client_session:str= Depends(get_client_session)
                         ):
    """
    ## Function
       <b>Return the status of the database and text server.  Some field returns depend on the user's security level.</b>

    ## Return Type
       models.ServerStatusItem (includes extra fields for admins)

    ## Status
       Status: Working

    ## Sample Call
         /v2/Session/Status/

    ## Notes
       2020-09-09 - client-session (id) is not longer needed except if extended admin information is required

    ## Potential Errors
       NA

    """
    global text_server_ver # solr ver
    admin = False

    # see if user is an admin
    if client_session is not None:
        ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)
        if ocd.verify_admin(session_info):
            admin = True
    else:
        ocd = opasCentralDBLib.opasCentralDB()
        
    db_ok = ocd.open_connection()
    solr_ok = opasAPISupportLib.check_solr_docs_connection()
    config_name = None
    mysql_ver = None
    hierarchical_server_ver = f"{text_server_ver}/{__version__}"
    
    if admin:
        config_name = localsecrets.CONFIG
        mysql_ver = ocd.get_mysql_version()
        try:
            server_status_item = models.ServerStatusItem(text_server_ok = solr_ok,
                                                         db_server_ok = db_ok,
                                                         dataSource = localsecrets.DATA_SOURCE, 
                                                         user_ip = request.client.host,
                                                         timeStamp = datetime.utcfromtimestamp(time.time()).strftime('%Y-%m-%dT%H:%M:%SZ'), 
                                                         text_server_version = hierarchical_server_ver,
                                                         serverContent=opasAPISupportLib.metadata_get_database_statistics(session_info), 
                                                         # admin only fields
                                                         text_server_url = localsecrets.SOLRURL,
                                                         opas_version = __version__, 
                                                         db_server_url = localsecrets.DBHOST,
                                                         db_server_version = mysql_ver,
                                                         cors_regex=localsecrets.CORS_REGEX, 
                                                         config_name = config_name,
                                                         user_count = 0
                                                         )

        except ValidationError as e:
            logger.warning("ValidationError", e.json())
            raise HTTPException(
                status_code=httpCodes.HTTP_400_BAD_REQUEST,
                detail=ERR_MSG_STATUS_DATA_ISSUE
            )
    else:
        try:
            if moreinfo:
                server_status_item = models.ServerStatusItem(text_server_ok = solr_ok,
                                                             db_server_ok = db_ok,
                                                             dataSource = localsecrets.DATA_SOURCE, 
                                                             text_server_version = hierarchical_server_ver,
                                                             opas_version = __version__, 
                                                             serverContent=opasAPISupportLib.metadata_get_database_statistics(session_info), 
                                                             user_ip = request.client.host,
                                                             timeStamp = datetime.utcfromtimestamp(time.time()).strftime('%Y-%m-%dT%H:%M:%SZ'), 
                                                             )
            else:
                server_status_item = models.ServerStatusItem(text_server_ok = solr_ok,
                                                             db_server_ok = db_ok,
                                                             dataSource = localsecrets.DATA_SOURCE, 
                                                             text_server_version = hierarchical_server_ver,
                                                             opas_version = __version__, 
                                                             user_ip = request.client.host,
                                                             timeStamp = datetime.utcfromtimestamp(time.time()).strftime('%Y-%m-%dT%H:%M:%SZ'), 
                                                             )
                
        except ValidationError as e:
            logger.warning("ValidationError", e.json())
            raise HTTPException(
                status_code=httpCodes.HTTP_400_BAD_REQUEST,
                detail=ERR_MSG_STATUS_DATA_ISSUE
            )

    ocd.close_connection()
    return server_status_item

#-----------------------------------------------------------------------------
@app.get("/v2/Session/Login/", response_model=models.SessionInfo, response_model_exclude_unset=True, tags=["Session"], summary=opasConfig.ENDPOINT_SUMMARY_LOGIN) # I like it under Users so I did them both.
def session_login(response: Response, 
                  request: Request,
                  username=None, 
                  password=None, 
                  grant_type=None, 
                  client_id:int=Depends(get_client_id), 
                  client_session:str= Depends(get_client_session)
                  ):
    """
    ## Function
       <b>Insecure login Authentication.</b>
    
       Supply username and password.
    
    ## Return Type
       models.LoginReturnItem
    
    ## Status
       This endpoint is working.
    
    ## Sample Call
         /v2/Session/BasicLogin/
    
    ## Notes
    
    ## Potential Errors
    
    """
    # for debugging client call
    opasDocPermissions.verify_header(request, "Login")
    log_endpoint(request, client_id=client_id, session_id=client_session)

    opas_session_cookie = request.cookies.get(opasConfig.OPASSESSIONID, None)
    if opas_session_cookie != client_session and opas_session_cookie is not None:
        # logout of any opas session
        opasDocPermissions.authserver_logout(opas_session_cookie, response=response)

    pads_session_info = opasDocPermissions.authserver_login(username=username, password=password, session_id=client_session) # don't pass session
    # New session id, need to get rest of session_info (below)
    session_id = pads_session_info.SessionId

    if pads_session_info.IsValidLogon != True:
        if pads_session_info.pads_disposition is not None:
            detail = f"{pads_session_info.pads_disposition}"
        else:
            detail = f"Login credential error. {pads_session_info.pads_status_response}"
        raise HTTPException(
            status_code=httpCodes.HTTP_401_UNAUTHORIZED, 
            detail=detail 
        )
    else:
        # need to do this, saves to db, but we're not directly using return values here
        session_info = opasDocPermissions.get_authserver_session_info(session_id, client_id, pads_session_info=pads_session_info)
        # Save it for eating later; most importantly, overwrite any existing cookie!
        #opas_session_cookie = request.cookies.get(opasConfig.OPASSESSIONID, None)
        if session_info.is_valid_login:
            response.set_cookie(
                OPASSESSIONID,
                value=f"{session_id}",
                domain=localsecrets.COOKIE_DOMAIN
            )
            logger.info("Successful login - saved OpasSessionID Cookie")
        # already should be in response per get_client_session

    try:
        login_return_item = models.LoginReturnItem(token_type = "bearer", 
                                                   session_id = session_id,
                                                   authenticated=pads_session_info.IsValidLogon,
                                                   error_message = None,
                                                   scope = None
                                                   )
    except ValidationError as e:
        logger.error(e.json())             
        detail = f"Validation Error {e}"
        # Solr Error
        raise HTTPException(
            status_code=httpCodes.HTTP_400_BAD_REQUEST, 
            detail=detail 
        )    
   
    return login_return_item

#-----------------------------------------------------------------------------
@app.get("/v2/Session/BasicLogin/", response_model=models.SessionInfo, response_model_exclude_unset=True, tags=["Session"], summary=opasConfig.ENDPOINT_SUMMARY_LOGIN_BASIC)
def session_login_basic(response: Response, 
                        request: Request,
                        client_id:int=Depends(get_client_id),
                        session_info=Depends(login_via_pads)
                        ):
    """
    ## Function
       <b>Basic login Authentication.</b>

       Supply username and password in the header which is secure in https.

    ## Return Type
       models.LoginReturnItem

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Session/BasicLogin/

    ## Notes

    ## Potential Errors

    """
    session_id = session_info.session_id

    if session_info is not None:
        ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=session_id, client_id=client_id)
        # Save it for later; most importantly, overwrite any existing cookie!
        if session_info.authenticated:
            logger.info("Successful basic login - saved OpasSessionID Cookie")
            opasAPISupportLib.save_opas_session_cookie(request, response, session_id)
            
        #opas_session_cookie = request.cookies.get(opasConfig.OPASSESSIONID, None)
        if session_info.is_valid_login:
            response.set_cookie(
                OPASSESSIONID,
                value=f"{session_id}",
                domain=localsecrets.COOKIE_DOMAIN
            )
            
    else:
        logger.error(f"Bad login")
        raise HTTPException(
            status_code=httpCodes.HTTP_400_BAD_REQUEST,
            detail=ERR_MSG_SESSION_ID_ERROR
        )

    return session_info

#-----------------------------------------------------------------------------
@app.get("/v2/Session/Logout/", response_model_exclude_unset=True, tags=["Session"], summary=opasConfig.ENDPOINT_SUMMARY_LOGOUT) # I like it under Users so I did them both.
def session_logout_user(response: Response, 
                        request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST), 
                        client_id:int=Depends(get_client_id), 
                        client_session:str= Depends(get_client_session)
                        ):  
    """
    ## Function
       <b>Close the user's session, and log them out.</b>
    ## Return Type
       models.LicenseInfoStruct

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Session/Logout/

    ## Notes

    ## Potential Errors

    """

    session_id = client_session
    # ocd = opasCentralDBLib.opasCentralDB()
    if session_id is not None and session_id != "":
        # session_info = ocd.get_session_from_db(session_id)
        # session_end_time = datetime.utcfromtimestamp(time.time())
        response.delete_cookie(key=OPASSESSIONID,path="/", domain=localsecrets.COOKIE_DOMAIN)
        ret_val = opasDocPermissions.authserver_logout(session_id, request=request, response=response)
        if ret_val:
            # logged out
           session_info = models.SessionInfo(session_id=session_id)

        #ocd, session_info = opasAPISupportLib.get_session_info(request, response,
                                                               #session_id=session_id, client_id=client_id)
    return session_info

#-----------------------------------------------------------------------------
@app.get("/v2/Database/TermCounts/", response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_TERM_COUNTS)  #  removed for now: response_model=models.DocumentList, 
async def database_term_counts(response: Response, 
                               request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                               termlist: str=Query(None, title=opasConfig.TITLE_TERMLIST, description=opasConfig.DESCRIPTION_TERMLIST),
                               termfield: str=Query("text", title=opasConfig.TITLE_TERMFIELD, description=opasConfig.DESCRIPTION_TERMFIELD),
                               #client_id:int=Depends(get_client_id), 
                               #client_session:str= Depends(get_client_session)
                               ):
    """
    ## Function
    <b>Get a list of term frequency counts (# of times term occurs across documents)</b>

    Can specify a field per the schema to limit it. e.g.,

       - text - all text
       - title - within titles
       - author -
       - author_bio_xml - in author bio
       - art_kwds - in keyword lists
       - art_lang - can look at frequency of en, fr, ... at article level
       - lang - can look at frequency of en, fr, ... at paragraph level
       - meta_xml - meta document data, including description of fixes, edits to documents

       Note: The field must be listed as stored, not just indexed.

    ## Return Type
       models.TermIndex

    ## Status
       Status: Working as described above

    ## Sample Call

    ## Notes

    See also: /v2/Database/TermCounts/

    ## Potential Errors

    ## Example Calls

    """
    ts = time.time()
    # no logging, no session info for this call...speed, speed, speed
    term_index_items = []
    param_error = False
    if termfield is None:
        termfield = "text"
    else:
        field_ok, field_info = opasSchemaHelper.solr_field_check(SOLR_DOCS, termfield)
        if field_ok == False:
            param_error = True
            statusMsg = f"Bad Request: Field {termfield} underfined"

    if param_error == False:
        results = {}  # results = {field1:{term:value, term:value, term:value}, field2:{term:value, term:value, term:value}}
        terms = shlex.split(termlist)
        for n in terms:
            try:
                # If specified as field:term
                nfield, nterms = n.split(":")
                result = opasAPISupportLib.get_term_count_list(nterms, nfield)
            except:
                # just list of terms, use against termfield parameter
                nterms = n.strip("', ")
                try:
                    result = opasAPISupportLib.get_term_count_list(nterms, term_field = termfield)
                    for key, value in result.items():
                        try:
                            results[termfield][key] = value
                        except:
                            results[termfield] = {}
                            results[termfield][key] = value
                except Exception as e:
                    detail = f"{e} - {result.error}. {result.error_description}"
                    logger.warning(detail)
                    # Solr Error
                    raise HTTPException(
                        status_code=result.httpcode, 
                        detail=detail 
                    )
            else:
                try:
                    a = results[nfield]
                    # exists, if we get here, so add it to the existing dict
                    for key, value in result.items():
                        results[nfield][key] = value
                except: #  new dict entry
                    results[nfield] = result

        response_info = models.ResponseInfo( listType="termindex", # this is a mistake in the GVPi API, should be termIndex
                                             scopeQuery=[f"Terms: {termlist}"],
                                             dataSource = localsecrets.DATA_SOURCE, 
                                             timestamp=datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)
                                             )

        response_info.count = 0
        if results != {}:
            for field, termdict in results.items():
                for term, value in termdict.items():
                    if value > 0:
                        item = models.TermIndexItem(field = field, 
                                                    term = term, 
                                                    termCount = value,
                                                    ) 
                        term_index_items.append(item)
                        logger.debug("termIndexGetInfo: %s", item)

        response_info.count = len(term_index_items)
        response_info.fullCountComplete = True
        term_index_struct = models.TermIndexStruct( responseInfo = response_info, 
                                                    responseSet = term_index_items
                                                    )

        term_index = models.TermIndex(termIndex = term_index_struct)

        if response_info.count > 0:
            matches = response_info.count
            term_index.termIndex.responseInfo.request = request.url._url
        else:
            matches = 0

        statusMsg = f"{matches} hits"
        logger.debug(statusMsg)

    if param_error:
        logging.warning(statusMsg)
        raise HTTPException(
            status_code=httpCodes.HTTP_400_BAD_REQUEST, 
            detail=statusMsg
        )

    log_endpoint_time(request, ts=ts)                  
    return term_index

#-----------------------------------------------------------------------------
@app.post("/v2/Database/AdvancedSearch/", response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_SEARCH_ADVANCED)  #  removed for now: response_model=models.DocumentList, 
async def database_advanced_search(response: Response, 
                                   request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                                   apimode: str=Header(None, title="API mode", description="Set the api mode to 'debug' or 'production' (default)"), 
                                   # Request body parameters - allows full specification of parameters in the body
                                   solrqueryspec: models.SolrQuerySpec=Body(None, embed=True),
                                   # Query parameters
                                   advanced_query: str=Query(None, title="Advanced Query (Solr Syntax)", description="Advanced Query in Solr syntax (see schema names)"),
                                   filter_query: str=Query(None, title="Advanced Query (Solr Syntax)", description="Advanced Query in Solr syntax (see schema names)"),
                                   return_fields: str=Query(None, title="Fields to return", description="Comma separated list of field names"),
                                   highlight_fields: str=Query("text_xml", title="Fields to return for highlighted matches", description="Comma separated list of field names"),
                                   def_type: str=Query("lucene", title="edisMax, disMax, lucene (standard) or None (lucene)", description="Query analyzer"),
                                   facet_fields: str=Query(None, title=opasConfig.TITLE_FACETFIELDS, description=opasConfig.DESCRIPTION_FACETFIELDS), 
                                   sort: str=Query("score desc", title="Field names to sort by", description="Comma separated list of field names, optionally each with direction (desc or asc)"),
                                   limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                                   offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                                   client_id:int=Depends(get_client_id), 
                                   client_session:str= Depends(get_client_session)
                                   ):
    """
    ## Function
    <b>Advanced search in Solr query syntax.</b>

    IMPORTANT NOTE: This endpoint is intended for client (user interface) developers to take advantage of the
    full Solr query functionality, while still returning the usual OPAS DocumentList return model, including conversion
    from XML to HTML.  If the developer wishes to specify the fields for return data, endpoint /v2/ExtendedSearch should be used.  

    This endpoint is not used, for example, in PEP-Easy because it isn't needed for basic query and retrieval operations which are built in
    to other endpoints.  PEP-Easy uses the v1 API exclusively (and not the Solr API or the v2 API).

    The documentation below on how to use the advanced query is intimately tied to the schemas (data structure based on the PEP DTDs).
    But it's not possible to provide query examples and sample data returns without tying them to a schema.  

    Currently, this endpoint only queries the Docs core (database), which is the main content database. Other cores include the Glossary core, the Authors core,
    and the References core.  Endpoint /v2/ExtendedSearch should be used to query other cores.

    ### Nested document search.

    Nested document search is used with the PEP Solr Schemas to search with paragraphs
    (or bibliographic entries--references) being the "atomic" unit of search (the record, in common database terms),
    while also using the context of the parent element and whole document metadata to filter.  So for example, you can find matches
    in paragraphs in "dreams", and the scope of the boolean logic of word searches must fall within
    a single paragraph (or reference).

    Per the Solr API, a nested document search must ensure that the matches for the different levels don't overlap or an error will occur.
    To prevent this, and to provide selectivity of the different child types, the art_level and parent_tag fields are included, which
    can be used to select the child (art_level:2), and the parent (art_level:1) and parent_tag (see below).

    For example, these PEP DTD elements (tags) are indexed as nested, art_level:2 documents in the pepwebdocs core
    with their parent tags as field <i>parent_tag</i>.

        * para in "doc" - this is mapped to the entire doc, minus the reference section (PEP Requirements).
          Advanced query must use "(p_body OR p_summaries OR p_appxs)"
            -- Note "doc" is a mapped (convenience) name for non-advanced query types and expanded to "(p_body OR p_summaries OR p_appxs)".  The entire document would be (p_body OR p_summaries OR "biblios" OR p_appxs)
        * para in "headings" - for advanced query use actual schema name "(p_heading)"
        * para in "quotes" - for advanced query use actual schema name "(p_quote)"
        * para in "dreams" - for advanced query use actual schema name "(p_dream)" 
        * para in "poems" - for advanced query use actual schema name "(p_poem)"
        * para in "notes" - for advanced query use actual schema name "(p_note)"
        * para in "dialogs" - for advanced query use actual schema name "(p_dialog)"
        * para in "panels" - for advanced query use actual schema name "(p_panel)"
        * para in "captions" - for advanced query use actual schema name "(p_caption)"
        * para in "biblios" - for advanced query use actual schema name "(p_biblio)"
            -- (each be/binc under PEP element bib, i.e., the references)
        * para in "appendixes" - for advanced query use actual schema name "(p_appendixes)"
        * para in "summaries" - for advanced query use actual schema name "(p_summaries)"

    Note that para is always the field name for convenience, but in some cases, it's logically something else, like a reference
    (which is comprised of an xml element be rather than xml element para), or even just cdata
    in the element

    Here's an example of a note "child" record:

        "id":"IJAPS.013.0191A.67",
        "parent_tag":"p_note",
        "para":"<p><i>Wikipedia</i>, Enlightenment, p. 1, emphasis added.</p>",
        "_version_":1655037031541112832,
        "art_level":2

    Solr keeps the relation to the parent for us, for which we use the special query syntax below.

    For SE and GW, child records include concordance data. For example:

        "id":"GW.001.0003A.1",
        "para":"<p lgrid=\"GWA3a3\" lgrx=\"SEA115a11\" lgrtype=\"GroupIDTrans\" lang=\"de\">Ich entschließe mich hier, ... einen einzelnen ...",
        "para_lgrid":"GWA3a3",
        "para_lgrx":["SEA115a11"]


    #### Sample nested queries

    <b>Find documents with paragraphs which contain "successful therapy" and "methods":</b>

    `{!parent which='art_level:1'} (art_level:2 AND parent_tag:(p_body OR p_summaries OR p_appxs) AND para:("successful therapy" AND methods))`

    <b>Find documents with paragraphs which contain Gabbard but NOT impact (the minus is shorthand for NOT):</b>

    `{!parent which='art_level:1'} (art_level:2 AND parent_tag:(p_body OR p_summaries OR p_appxs) AND para:(Gabbard AND -impact))`

    <b>Find documents with the words flying and falling in the same paragraph in a dream:</b>

    `{!parent which="art_level:1"} art_level:2 AND parent_tag:p_dream AND para:(flying AND falling)`

    To return the matching "full" paras as records, you can directly search the child documents.  However, you will not
    get the parent document data as part of the return in this case (the fields will be in the return records, but the data will just be 'null').
    The matching paras will be in the field para in the return records, and there will be no marked hits.

    ##### Child Only Query Example

    `parent_tag:p_dream AND para:(flying AND wings)`

    ##### Child Only Return data example (abbreviated) from above example (null fields removed)

       ```
       "response":{"numFound":3,"start":0,"maxScore":11.844459,"docs":[
           {
             "parent_tag":"p_dream",
             "para":"<p><i>I'm on an island beach looking out over a large body of water. High above the beach just making its way out over the water is an enormous flying contraption whose wings appear to be made of silk that is beige or golden in color. Roosting on the wings are exotic birds whose plumage is also this color. It's moving slowly out over the water. It's a remarkable sight</i>.</p>",
             "art_level":2,
             "score":11.844459},
           {
             "parent_tag":"p_dream",
             "para":"<p>I was with my brother, going to a meeting. I felt sick, and soiled my pants. It was a mess. Then I showed him where he could get fresh clothes—odd, <impx type=\"TERM2\" rx=\"ZBK.069.0001c.YN0004867612400\" grpname=\"CAUSE\">cause</impx> I was the one that made the mess.—Then we're back at the meeting, where I should be able to find my brother, but I can't. I'm looking all over, moving faster, and then…. I started to fly! A woman applauded and encouraged my flying. And I said “I like to do it this smooth way, don't need to flap wings harder.” Then I was flying over a college campus, a festive scene, but then I realized I'd forgotten my brother and felt guilty.</p>",
             "art_level":2,
             "score":10.832498},
           {
             "parent_tag":"p_dream",
             "para":"<p2>eyes, but at the same time I am full of joy, because it is a beautiful <impx type=\"TERM2\" rx=\"ZBK.069.0001d.YN0013300865870\" grpname=\"DEATH\">death</impx>. At this <impx type=\"TERM2\" rx=\"ZBK.069.0001m.YP0001417964900\" grpname=\"MOMENT\">moment</impx> the sliding stops, and I see someone who is flying. He glides downward several times; then he again wings upwards. I am watching him at these performances, and a young man with a pince nez is also looking up. I am no longer alone. He is singing a very nice Russian song, which I have heard already. As the aviator disappears, the scene changes and I am no longer in the N<su>***</su> Valley in G<su>***</su> but in the S<su>***</su> Park in B<su>***</su>, and I am singing or humming the song too. He asks me whether he may accompany me. I tell him that he may walk with me to the optometrist. A piece of my lorgnette had broken off, and I want to have it repaired. I start to cross the street at the S<su>***</su> Park, but the young man has disappeared. Then I awake.</p2>",
             "art_level":2,
             "score":8.666403
           }
           ]
       ```

    ### Thesaurus matching

    Solr thesaurus matching is either on or off for a field, it's not something you can specify as a query parameter to Solr.
    So for thesaurus matches, where desirable, a secondary field is defined with the suffix _syn that has the PEP thesaurus enabled.

    This currently includes
        * text -> text_syn
        * title -> title_syn
        * para -> para_syn

    ### Final Notes

       * Solr advanced queries are case sensitive. The boolean connector AND must be in caps.
       * important to understand the applicable schema to query (unless you only search the default field text)

    ## Return Type
       models.DocumentList

    ## Status
       Status: Still in Development and testing

    """
    opasDocPermissions.verify_header(request, "AdvancedSearch") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)
    session_id = session_info.session_id
    try:
        apimode = apimode.lower()
    except:
        apimode = "production"

    if re.search(r"/Search/", request.url._url):
        logger.debug("Search Request: %s", request.url._url)

    #For the interactive docs, watch for the schema coming back and ignore if that's the case
    if solrqueryspec is not None:
        if solrqueryspec.label == "string":
            solrqueryspec = None

    solr_query_spec = \
        opasQueryHelper.parse_to_query_spec(solr_query_spec=solrqueryspec, 
                                            query=advanced_query, 
                                            filter_query = filter_query,
                                            def_type = def_type, # edisMax, disMax, or None
                                            summary_fields=return_fields, 
                                            highlight_fields = highlight_fields, 
                                            facet_fields = facet_fields, 
                                            sort = sort,
                                            limit=limit, 
                                            offset=offset, 
                                            req_url=request.url._url
                                            )
    # try the query
    ret_val, ret_status = search_text_qs(solr_query_spec,
                                         #authenticated=session_info.authenticated
                                         session_info=session_info
                                         )

    #  if there's a Solr server error in the call, it returns a non-200 ret_status[0]
    if ret_status[0] != httpCodes.HTTP_200_OK:
        #  throw an exception rather than return an object (which will fail)
        #TODO: should we let this fall through to log the endpoint even though there was an error?
        return ret_val # function returns - models.ErrorReturn
        #raise HTTPException(
            #status_code=ret_status[0], 
            #detail=f"Bad Solr Search Request. {ret_status[1].reason}:{ret_status[1].body}"
        #)
    else:
        if ret_val != {}:
            matches = len(ret_val.documentList.responseSet)
            ret_val.documentList.responseInfo.request = request.url._url
        else:
            matches = 0

        statusMsg = f"{matches} hits"
        logger.debug(statusMsg)

    # client_host = request.client.host
    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_ADVANCEDSEARCH,
                                api_endpoint_method=opasCentralDBLib.API_ENDPOINT_METHOD_POST, 
                                session_info=session_info, 
                                params=request.url._url,
                                return_status_code = ret_status[0], 
                                status_message=statusMsg
                                )

    return ret_val

#---------------------------------------------------------------------------------------------------------
@app.post("/v2/Database/ExtendedSearch/", response_model=models.SolrReturnList, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_EXTENDED_SEARCH)  #  response_model_exclude_unset=True removed for now: response_model=models.DocumentList, 
async def database_extendedsearch(response: Response,
                                  request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                                  solrQuerySpec: models.SolrQuerySpec=None, # allows full specification of parameters in the body
                                  api_key: APIKey = Depends(get_api_key),
                                  client_id:int=Depends(get_client_id), 
                                  client_session:str= Depends(get_client_session)
                                  ):
    """
    ## Function
    <b>Search_extended Solr style</b>

    Perform a solr query using solr parameter definitions with any server core.

    API_KEY required.

    #TODO: For security, the endpoint is configured not to allow the return of PEP text_xml. Now there's an API_KEY requirement,
           consider removing constraint

    IMPORTANT NOTE: This endpoint is intended for client (user interface) developers to take advantage of the
    full Solr query functionality beyond what the current endpoints allow, without directly connecting to Solr.
    It provides a flexible Solr return set, but offers a bit of a hand by integrating highlighted (match) data with
    return data, which are returned in separate lists in the normal Solr return structure.  For flexibility and expandability,
    this endpoint requires parameters in the REST call body, according to the models.SolrQuerySpec structure
    rather than as URL arguments.  To test, call with an REST API test tool like Postman. Postman
    also provides a nice 'pretty printed' data return.

    The API user must be logged in to a valid account currently to use this for full-text return (return size is limited).

    The documentation on how to use the advanced query is intimately tied to the schemas (data structure based on the PEP DTDs).
    But it's not possible to provide query examples and sample data returns without tying them to a schema.

    This endpoint is not used in PEP-Easy because it isn't needed to provide any of the PEP-Easy functionality, all of which are built in
    to other endpoints.  PEP-Easy functionality only requires what was present in the v1 API (and not the expanded v2 API).

    ## Return Type
       SolrReturnList - flexible field solr results in the responseSet of an otherwise OPAS standard structure 

    #### Sample queries

    ##### <b>Find documents with paragraphs which contain Othogenic school, returning art_id, title, and art_citeas_xml:</b>

    ###### Request Body
    ```
    { 
        "core" : "pepwebdocs",
        "solrQuery" : {
                        "searchQ" : "Orthogenic\u0020school",
                        "fullReturn": false
        },
        "solrQueryOpts" : {
            "returnFields": "art_id, title, art_citeas_xml",
            "hlFields": "text_xml",
            "hlFragsize": 100,
            "hlSnippets" : 10,
            "hlUsePhraseHighlighter" : "true"
        }
    }
    ```


    ## Status
       Status: New, created 2020-01-03 and now in development and testing 

    ## Notes
       See also /v2/Database/AdvancedSearch/ for an alternative endpoint which returns data
       in OPAS DocumentList format.

    ## Potential Errors

    """
    opasDocPermissions.verify_header(request, "ExtendedSearch") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)
    # session_id = session_info.session_id 
    logger.debug("Solr Search Request: %s", request.url._url)
    solr_ret_list = None

    if solrQuerySpec is not None:
        solrQuery = solrQuerySpec.solrQuery
        if solrQuery is not None:
            solrQueryOpts = solrQuerySpec.solrQueryOpts
            if solrQuerySpec.returnFields is None:
                solrQuerySpec.returnFields = "id, file_classification" #  need to always return id
            else:
                solrQuerySpec.returnFields += ", id, file_classification"

            # don't let them bring back full-text content in at least PEP schema fields in docs or glossary
            solrQuerySpec.returnFields = re.sub("(,\s*?)?[^A-z0-9](text_xml|para|term_def_rest_xml)[^A-z0-9]", "", solrQuerySpec.returnFields)
            # limited return, no full-text, EVER (because it could be used to bypass the embargo.)
            fragSize = opasConfig.DEFAULT_KWIC_CONTENT_LENGTH 

            #TODO allow core parameter here
            if solrQuerySpec.core is not None:
                try:
                    from configLib.opasCoreConfig import EXTENDED_CORES
                    solr_core = EXTENDED_CORES.get(solrQuerySpec.core, None)
                except Exception as e:
                    detail=ERR_MSG_CORE_SPEC_ERROR + f" {e}"
                    logger.error(detail)
                    raise HTTPException(
                        status_code=httpCodes.HTTP_400_BAD_REQUEST, 
                        detail=detail
                    )
                else:
                    if solr_core is None:
                        detail=f"Bad Extended Request. Core not specified."
                        logger.warning(detail)
                        raise HTTPException(
                            status_code=httpCodes.HTTP_400_BAD_REQUEST, 
                            detail=detail
                        )
            else:
                solr_core = solr.SolrConnection(localsecrets.SOLRURL + solrQuerySpec.core, http_user=localsecrets.SOLRUSER, http_pass=localsecrets.SOLRPW)

            # see if highlight fields are selected
            hl = solrQueryOpts.hlFields is not None

            try:
                if hl:
                    results = solr_core.query(q = solrQuery.searchQ,  
                                              fq = solrQuery.filterQ,
                                              q_op = solrQueryOpts.qOper.upper(), 
                                              fields = solrQuerySpec.returnFields, 
                                              # highlighting parameters
                                              hl = "true",
                                              hl_method = solrQueryOpts.hlMethod.lower(),
                                              hl_bs_type="SENTENCE", 
                                              hl_fl = solrQueryOpts.hlFields,
                                              hl_fragsize = fragSize,  # from above
                                              hl_maxAnalyzedChars=solrQueryOpts.hlMaxAnalyzedChars if solrQueryOpts.hlMaxAnalyzedChars>0 else opasConfig.SOLR_FULL_TEXT_MAX_ANALYZED_CHARS, 
                                              hl_multiterm = solrQueryOpts.hlMultiterm, # def "true", # only if highlighting is on
                                              hl_multitermQuery="true",
                                              hl_highlightMultiTerm="true",
                                              hl_weightMatches="true", 
                                              hl_tag_post = solrQueryOpts.hlTagPost,
                                              hl_tag_pre = solrQueryOpts.hlTagPre,
                                              hl_snippets = solrQueryOpts.hlSnippets,
                                              #hl_encoder = "html", # (doesn't work for standard, doesn't do anything we want in unified)
                                              hl_usePhraseHighlighter = solrQueryOpts.hlUsePhraseHighlighter, # only if highlighting is on
                                              #hl_q = solrQueryOpts.hlQ, # doesn't help with phrases; searches for None if it's none!
                                              # morelikethis parameters
                                              mlt = solrQueryOpts.moreLikeThisCount > 0, # if >0 turns on morelike this
                                              mlt_fl = solrQueryOpts.moreLikeThisFields, 
                                              mlt_count = solrQueryOpts.moreLikeThisCount,
                                              # paging parameters
                                              rows = solrQuerySpec.limit,
                                              start = solrQuerySpec.offset
                                              )
                    solr_ret_list_items = []
                    for n in results.results:
                        rid = n["id"]
                        n["highlighting"] = results.highlighting[rid]  
                        item = models.SolrReturnItem(solrRet=n)
                        solr_ret_list_items.append(item)
                else:
                    results = solr_core.query(q = solrQuery.searchQ,  
                                              fq = solrQuery.filterQ,
                                              q_op = "AND", 
                                              fields = solrQuerySpec.returnFields,
                                              # morelikethis parameters
                                              mlt = solrQueryOpts.moreLikeThisCount > 0, # if >0 turns on morelike this
                                              mlt_fl = solrQueryOpts.moreLikeThisFields, 
                                              mlt_count = solrQueryOpts.moreLikeThisCount,
                                              # paging parameters
                                              rows = solrQuerySpec.limit,
                                              start = solrQuerySpec.offset
                                              )
                    solr_ret_list_items = []
                    for n in results.results:
                        item = models.SolrReturnItem(solrRet=n)
                        solr_ret_list_items.append(item)

                    ret_status = httpCodes.HTTP_200_OK

            except solr.SolrException as e:
                #if e.httpcode == 400:
                    #ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Search syntax error", error_description=f"There's an error in your input {e.reason}")
                #else:
                    #ret_val = models.ErrorReturn(httpcode=e.httpcode, error="Solr engine returned an unknown error", error_description=f"Solr engine returned error {e.httpcode} - {e.reason}")
                # statusMsg = f"Solr Runtime Search Error: {e.reason}"
                ret_status = (e.httpcode, e)
                raise HTTPException(
                    status_code=ret_status[0], 
                    detail=f"Bad Solr Search Request. {ret_status[1].reason}:{ret_status[1].body}"
                )

            statusMsg = f"RAW Q:{solrQuery.searchQ} / F:{solrQuery.filterQ} N: {results._numFound}"
            logger.debug(statusMsg)

            response_info = models.ResponseInfo( count = len(solr_ret_list_items),
                                                 fullCount = results._numFound,
                                                 limit = solrQuerySpec.limit,
                                                 offset = solrQuerySpec.offset,
                                                 listType="advancedsearchlist",
                                                 fullCountComplete = solrQuerySpec.limit >= results._numFound,  
                                                 dataSource = localsecrets.DATA_SOURCE, 
                                                 timeStamp = datetime.utcfromtimestamp(time.time()).strftime(TIME_FORMAT_STR)                     
                                                 )
            solr_list_struct = models.SolrReturnStruct( responseInfo = response_info, 
                                                        responseSet = solr_ret_list_items
                                                        )

            solr_ret_list = models.SolrReturnList(solrRetList = solr_list_struct)


            # client_host = request.client.host
            ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_SEARCH,
                                        session_info=session_info, 
                                        params=request.url._url,
                                        return_status_code = ret_status, 
                                        status_message=statusMsg
                                        )

    return solr_ret_list

#---------------------------------------------------------------------------------------------------------
@app.get("/v2/Database/SearchParagraphs/", tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_SEARCH_PARAGRAPHS)  #  response_model_exclude_unset=True removed for now: response_model=models.DocumentList, 
async def database_search_paragraphs(response: Response, 
                                     request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                                     # request body parameters
                                     #termlist: models.SolrQueryTermList=None, # experimental, allows full specification in body per models.QuerySpecification
                                     # query parameters
                                     paratext: str=Query(None, title=opasConfig.TITLE_PARATEXT, description=opasConfig.DESCRIPTION_PARATEXT),
                                     parascope: str=Query("doc", title=opasConfig.TITLE_PARASCOPE, description=opasConfig.DESCRIPTION_PARASCOPE),
                                     synonyms: bool=Query(False, title=opasConfig.TITLE_SYNONYMS_BOOLEAN, description=opasConfig.DESCRIPTION_SYNONYMS_BOOLEAN),
                                     # query parameters that get mapped to filters (Solr query filter)
                                     sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME),  
                                     sourcecode: str=Query(None, title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE), 
                                     sourcetype: str=Query(None, title=opasConfig.TITLE_SOURCETYPE, description=opasConfig.DESCRIPTION_PARAM_SOURCETYPE),
                                     sourcelangcode: str=Query(None, min_length=2, title=opasConfig.TITLE_SOURCELANGCODE, description=opasConfig.DESCRIPTION_SOURCELANGCODE),
                                     volume: str=Query(None, title=opasConfig.TITLE_VOLUMENUMBER, description=opasConfig.DESCRIPTION_VOLUMENUMBER), 
                                     author: str=Query(None, title=opasConfig.TITLE_AUTHOR, description=opasConfig.DESCRIPTION_AUTHOR), 
                                     title: str=Query(None, title=opasConfig.TITLE_TITLE, description=opasConfig.DESCRIPTION_TITLE),
                                     articletype: str=Query(None, title=opasConfig.TITLE_ARTICLETYPE, description=opasConfig.DESCRIPTION_ARTICLETYPE),
                                     startyear: str=Query(None, title=opasConfig.TITLE_STARTYEAR, description=opasConfig.DESCRIPTION_STARTYEAR), 
                                     endyear: str=Query(None, title=opasConfig.TITLE_ENDYEAR, description=opasConfig.DESCRIPTION_ENDYEAR), 
                                     citecount: str=Query(None, title=opasConfig.TITLE_CITECOUNT, description=opasConfig.DESCRIPTION_CITECOUNT),   
                                     viewcount: str=Query(None, title=opasConfig.TITLE_VIEWCOUNT, description=opasConfig.DESCRIPTION_VIEWCOUNT),
                                     viewperiod: int=Query(4, title=opasConfig.TITLE_VIEWPERIOD, description=opasConfig.DESCRIPTION_VIEWPERIOD),     
                                     # return set control
                                     #returnfields: str=Query(None, title="Fields to return (see limitations)", description="Comma separated list of field names"),
                                     abstract:bool=Query(False, title="Return an abstract with each match", description="True to return an abstract"),
                                     similarcount: int=Query(0, title=opasConfig.TITLE_SIMILARCOUNT, description=opasConfig.DESCRIPTION_SIMILARCOUNT),
                                     highlightlimit: int=Query(opasConfig.DEFAULT_MAX_KWIC_RETURNS, title=opasConfig.TITLE_MAX_KWIC_COUNT, description=opasConfig.DESCRIPTION_MAX_KWIC_COUNT),
                                     facetfields: str=Query(None, title=opasConfig.TITLE_FACETFIELDS, description=opasConfig.DESCRIPTION_FACETFIELDS), 
                                     facetmincount: int=Query(1, title="Minimum count to return a facet"),
                                     facetlimit: int=Query(10, title="Maximum number of facet values to return"),
                                     facetoffset: int=Query(0, title="Offset that can be used for paging through a facet"),
                                     sort: str=Query("score desc", title=opasConfig.TITLE_SORT, description=opasConfig.DESCRIPTION_SORT),
                                     limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                                     offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                                     client_id:int=Depends(get_client_id), 
                                     client_session:str= Depends(get_client_session)
                                     ):
    """
    ## Function
       <b>Convenience function to search the database by basic criteria (as exemplified in PEP-Easy).</b>

       Multiple word search is within markup terminals, namely a paragraph.  The scope is the parent of the paragraph
       and this currently supports:
        - doc
        - dreams
        - dialogs
        - quotes
        - poems
        - references (each reference is the equivalent of paragraph)

    ## Return Type
       models.DocumentList

    ## Status
       Status: In Development

    ## Sample Call

    ## Notes
       6/2020 - The returnfields parameter was removed as not useful here.

    ## Limitations

    ## Potential Errors

    """

    # for debugging client call
    opasDocPermissions.verify_header(request, "SearchParas")
    log_endpoint(request, client_id=client_id, session_id=client_session)

    errors, mod_args = opasQueryHelper.check_search_args(
                                             paratext=paratext,
                                             author=author,
                                             title=title,
                                             startyear=startyear,
                                             endyear=endyear
                                           )
    if errors:
        detail = "Error 425: Too few characters or unbalanced."
        print(detail)
        raise HTTPException(
            status_code=opasConfig.httpCodes.HTTP_425_TOO_EARLY,
            detail=detail
        )

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    # session_id = session_info.session_id 
    logger.debug("Search Request: %s", request.url._url)

    # this does intelligent processing of the query parameters and returns a
    # smaller set of solr oriented params (per pydantic model
    # SolrQueryParameters), ready to use
    solr_query_spec = \
        opasQueryHelper.parse_search_query_parameters(para_textsearch=paratext,
                                                      para_scope=parascope, 
                                                      #solrQueryTermList=termlist,
                                                      synonyms=synonyms,
                                                      similar_count=similarcount, 
                                                      source_name=sourcename,
                                                      source_code=sourcecode,
                                                      source_lang_code=sourcelangcode,
                                                      vol=volume,
                                                      author=author,
                                                      title=title,
                                                      startyear=startyear,
                                                      endyear=endyear, 
                                                      #references=references,
                                                      articletype=articletype, 
                                                      citecount=citecount,
                                                      viewcount=viewcount,
                                                      viewperiod=viewperiod,
                                                      highlightlimit=highlightlimit, 
                                                      facetfields=facetfields, 
                                                      facetmincount=facetmincount,
                                                      facetlimit=facetlimit,
                                                      facetoffset=facetoffset,
                                                      abstract_requested=abstract, 
                                                      limit=limit,
                                                      offset=offset,
                                                      sort=sort,
                                                      req_url = request.url._url
                                                      )

    solr_query_params = solr_query_spec.solrQuery
    # solr_query_opts = solr_query_spec.solrQueryOpts

    ret_val, ret_status = search_text_qs(solr_query_spec,
                                         extra_context_len=opasConfig.DEFAULT_KWIC_CONTENT_LENGTH,
                                         limit=limit,
                                         offset=offset,
                                         req_url=request.url._url, 
                                         #authenticated=session_info.authenticated
                                         session_info=session_info
                                         )

    #  if there's a Solr server error in the call, it returns a non-200 ret_status[0]
    if ret_status[0] != httpCodes.HTTP_200_OK:
        #  throw an exception rather than return an object (which will fail)
        try:
            detail=f"Bad Solr Search Request. {ret_status[1].reason}:{ret_status[1].body}"
        except:
            detail = "Bad Solr Search Request"
            
        raise HTTPException(
            status_code=ret_status[0],
            detail=detail
        )

    if ret_val != {}:
        matches = len(ret_val.documentList.responseSet)
    else:
        matches = 0

    statusMsg = f"{matches} hits"
    logger.debug(statusMsg)

    # client_host = request.client.host
    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_SEARCH,
                                session_info=session_info, 
                                params=request.url._url,
                                return_status_code = ret_status[0], 
                                status_message=statusMsg
                                )

    return ret_val

#---------------------------------------------------------------------------------------------------------
@app.post("/v2/Database/Search/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_SEARCH_V3)
async def database_search_v2b( response: Response, 
                               request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                               qtermlist: models.SolrQueryTermList=Body(None, embed=True, title=opasConfig.TITLE_QTERMLIST, decription=opasConfig.DESCRIPTION_QTERMLIST), # allows full specification
                               fulltext1: str=Query(None, title=opasConfig.TITLE_FULLTEXT1, description=opasConfig.DESCRIPTION_FULLTEXT1),
                               smarttext: str=Query(None, title=opasConfig.TITLE_SMARTSEARCH, description=opasConfig.DESCRIPTION_SMARTSEARCH),
                               paratext: str=Query(None, title=opasConfig.TITLE_PARATEXT, description=opasConfig.DESCRIPTION_PARATEXT),
                               parascope: str=Query(None, title=opasConfig.TITLE_PARASCOPE, description=opasConfig.DESCRIPTION_PARASCOPE),
                               synonyms: bool=Query(False, title=opasConfig.TITLE_SYNONYMS_BOOLEAN, description=opasConfig.DESCRIPTION_SYNONYMS_BOOLEAN),
                               # filters (Solr query filter)
                               sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME, min_length=2),  
                               sourcecode: str=Query(None, title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE, min_length=2), 
                               sourcetype: str=Query(None, title=opasConfig.TITLE_SOURCETYPE, description=opasConfig.DESCRIPTION_PARAM_SOURCETYPE), 
                               sourcelangcode: str=Query(None, min_length=2, title=opasConfig.TITLE_SOURCELANGCODE, description=opasConfig.DESCRIPTION_SOURCELANGCODE), 
                               volume: str=Query(None, title=opasConfig.TITLE_VOLUMENUMBER, description=opasConfig.DESCRIPTION_VOLUMENUMBER), 
                               issue: str=Query(None, title=opasConfig.TITLE_ISSUE, description=opasConfig.DESCRIPTION_ISSUE),
                               author: str=Query(None, title=opasConfig.TITLE_AUTHOR, description=opasConfig.DESCRIPTION_AUTHOR), 
                               title: str=Query(None, title=opasConfig.TITLE_TITLE, description=opasConfig.DESCRIPTION_TITLE),
                               articletype: str=Query(None, title=opasConfig.TITLE_ARTICLETYPE, description=opasConfig.DESCRIPTION_ARTICLETYPE),
                               startyear: str=Query(None, title=opasConfig.TITLE_STARTYEAR, description=opasConfig.DESCRIPTION_STARTYEAR), 
                               endyear: str=Query(None, title=opasConfig.TITLE_ENDYEAR, description=opasConfig.DESCRIPTION_ENDYEAR), 
                               citecount: str=Query(None, title=opasConfig.TITLE_CITECOUNT, description=opasConfig.DESCRIPTION_CITECOUNT),   
                               viewcount: str=Query(None, title=opasConfig.TITLE_VIEWCOUNT, description=opasConfig.DESCRIPTION_VIEWCOUNT),    
                               viewperiod: int=Query(4, title=opasConfig.TITLE_VIEWPERIOD, description=opasConfig.DESCRIPTION_VIEWPERIOD),     
                               # return set control
                               #returnfields: str=Query(None, title="Fields to return (see limitations)", description="Comma separated list of field names"),
                               abstract:bool=Query(False, title="Return an abstract with each match", description="True to return an abstract"),
                               formatrequested: str=Query("HTML", title=opasConfig.TITLE_RETURNFORMATS, description=opasConfig.DESCRIPTION_RETURNFORMATS),
                               similarcount: int=Query(0, title=opasConfig.TITLE_SIMILARCOUNT, description=opasConfig.DESCRIPTION_SIMILARCOUNT),
                               highlightlimit: int=Query(opasConfig.DEFAULT_MAX_KWIC_RETURNS, title=opasConfig.TITLE_MAX_KWIC_COUNT, description=opasConfig.DESCRIPTION_MAX_KWIC_COUNT),
                               facetfields: str=Query(None, title=opasConfig.TITLE_FACETFIELDS, description=opasConfig.DESCRIPTION_FACETFIELDS), 
                               facetmincount: int=Query(1, title="Minimum count to return a facet"),
                               facetlimit: int=Query(15, title="Maximum number of facet values to return"),
                               facetoffset: int=Query(0, title="Offset that can be used for paging through a facet"),
                               sort: str=Query("score desc", title=opasConfig.TITLE_SORT, description=opasConfig.DESCRIPTION_SORT),
                               limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                               offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                               client_id:int=Depends(get_client_id), 
                               client_session:str= Depends(get_client_session)
                             ):
    """
    ## Function
       <b>Search the database per one or more of the fields specified.</b>

       In this v3 PUT version, search terms can also be put into "termlist", so synonyms can be turned
         on term by term, defined as this model. (This is the only difference, at this development stage
         (where v2 is really the current version))

    ## Return Type
       models.DocumentList

    ## Status
       Status: In Development

       - in perpetual development to extend and improve features
          - smarttext now detects title search under much more restrictive inputs
            due to user input where terrm search was favored
       - Other engines, e.g., disMax, edisMax also not yet implemented


    ## Sample Call
         PUT: /v2/Database/Search/?author=Blum&sourcecode=AOP&fulltext1=transference

    ## Notes
        - 2020-09-10 removed returnFields...covered in querySpec for POST version
        - Sample qtermlist in body
        ```
        {
            "qtermlist": {
                "comment": "comments can be inserted like this and will be ignored",
                "artLevel": 2,
                "qt": [{
                        "words": "action",
                        "field": "para",
                        "synonyms": "false"
                    },
                    {
                        "words": "unconscious",
                        "field": "para",
                        "synonyms": "true"
                    }
                ],
                "qf": [{
                    "words": "AJP",
                    "field": "art_sourcecode"
                }],
                "solrQueryOpts": {
                    "hlFields": "text_xml"
                }
            }
        }
        ```

    """
    ts = time.time()
    opasDocPermissions.verify_header(request, "SearchV3") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    errors, mod_args = opasQueryHelper.check_search_args(
                                             smarttext=smarttext,
                                             fulltext1=fulltext1,
                                             paratext=paratext,
                                             author=author,
                                             title=title,
                                             startyear=startyear,
                                             endyear=endyear
                                           )
    if errors:
        detail = "Error 425: Too few characters or unbalanced."
        print(detail)
        raise HTTPException(
            status_code=opasConfig.httpCodes.HTTP_425_TOO_EARLY,
            detail=detail
        )

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    # session_id = session_info.session_id 

    if re.search(r"/Search/", request.url._url):
        logger.debug("Search Request: %s", request.url._url)

    analysis_mode = False

    # don't set parascope, unless they set paratext and forgot to set parascope
    if paratext is not None and parascope is None:
        parascope = "doc"

    # Handle the openapi passing back in the example by default
    try:
        if qtermlist.artLevel == 0:
            qtermlist = None
    except:
        qtermlist = None

    # this does intelligent processing of the query parameters and returns a smaller set of solr oriented         
    # params (per pydantic model SolrQuery), ready to use
    solr_query_spec = \
        opasQueryHelper.parse_search_query_parameters(solrQueryTermList=qtermlist,
                                                      source_name=sourcename,
                                                      source_code=sourcecode,
                                                      source_type=sourcetype,
                                                      source_lang_code=sourcelangcode,
                                                      para_textsearch=mod_args.get("paratext", None), # search within paragraphs
                                                      para_scope=parascope, # scope for par_search
                                                      similar_count=similarcount, # Turn on morelikethis for the search, return this many similar docs for each
                                                      fulltext1=mod_args.get("fulltext1", None),  # more flexible search, including fields, anywhere in the doc, across paras
                                                      smarttext=mod_args.get("smarttext", None), # experimental detection of what user wants to query
                                                      synonyms=synonyms, 
                                                      vol=volume,
                                                      issue=issue,
                                                      author=author,
                                                      title=title,
                                                      articletype=articletype, 
                                                      startyear=startyear,
                                                      endyear=endyear,
                                                      citecount=citecount,
                                                      viewcount=viewcount,
                                                      viewperiod=viewperiod,
                                                      highlightlimit=highlightlimit, 
                                                      facetfields=facetfields,
                                                      facetmincount=facetmincount,
                                                      facetlimit=facetlimit,
                                                      facetoffset=facetoffset,                                                        
                                                      abstract_requested=abstract,
                                                      formatrequested=formatrequested, 
                                                      limit=limit,
                                                      offset=offset,
                                                      sort=sort,
                                                      req_url = request.url._url
                                                      )

    ret_val, ret_status = search_text_qs(solr_query_spec, 
                                         extra_context_len=opasConfig.DEFAULT_KWIC_CONTENT_LENGTH,
                                         limit=limit,
                                         offset=offset,
                                         session_info=session_info
                                         )

    #  if there's a Solr server error in the call, it returns a non-200 ret_status[0]
    if ret_status[0] != httpCodes.HTTP_200_OK:
        #  throw an exception rather than return an object (which will fail)
        try:
            detail=f"Bad Solr Search Request. {ret_status[1].reason}:{ret_status[1].body}"
        except:
            detail = "Bad Solr Search Request"
            
        raise HTTPException(
            status_code=ret_status[0],
            detail=detail
        )

    if ret_val != {}:
        matches = len(ret_val.documentList.responseSet)
        # ret_val.documentList.responseInfo.request = request.url._url
    else:
        matches = 0

    logger.debug(f"....matches = {matches}")
    # fill in additional return structure status info
    statusMsg = f"{matches} hits; similar documents per result requested:{similarcount}; queryAnalysis: {analysis_mode}"
    logger.debug("Done with search.")

    # client_host = request.client.host

    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_SEARCH,
                                api_endpoint_method=opasCentralDBLib.API_ENDPOINT_METHOD_POST, 
                                session_info=session_info,
                                params=request.url._url,
                                return_status_code = ret_status[0], 
                                status_message=statusMsg
                                )

    log_endpoint_time(request, ts=ts)
    return ret_val

#---------------------------------------------------------------------------------------------------------
@app.get("/v2/Database/Search/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_SEARCH_V2)
async def database_search_v2(response: Response, 
                             request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                             fulltext1: str=Query(None, title=opasConfig.TITLE_FULLTEXT1, description=opasConfig.DESCRIPTION_FULLTEXT1),
                             smarttext: str=Query(None, title=opasConfig.TITLE_SMARTSEARCH, description=opasConfig.DESCRIPTION_SMARTSEARCH),
                             paratext: str=Query(None, title=opasConfig.TITLE_PARATEXT, description=opasConfig.DESCRIPTION_PARATEXT),
                             parascope: str=Query(None, title=opasConfig.TITLE_PARASCOPE, description=opasConfig.DESCRIPTION_PARASCOPE),
                             synonyms: bool=Query(False, title=opasConfig.TITLE_SYNONYMS_BOOLEAN, description=opasConfig.DESCRIPTION_SYNONYMS_BOOLEAN),
                             # filters (Solr query filter)
                             sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME, min_length=2),  
                             sourcecode: str=Query(None, title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE, min_length=2), 
                             sourcetype: str=Query(None, title=opasConfig.TITLE_SOURCETYPE, description=opasConfig.DESCRIPTION_PARAM_SOURCETYPE), 
                             sourcelangcode: str=Query(None, min_length=2, title=opasConfig.TITLE_SOURCELANGCODE, description=opasConfig.DESCRIPTION_SOURCELANGCODE), 
                             volume: str=Query(None, title=opasConfig.TITLE_VOLUMENUMBER, description=opasConfig.DESCRIPTION_VOLUMENUMBER), 
                             issue: str=Query(None, title=opasConfig.TITLE_ISSUE, description=opasConfig.DESCRIPTION_ISSUE),
                             author: str=Query(None, title=opasConfig.TITLE_AUTHOR, description=opasConfig.DESCRIPTION_AUTHOR), 
                             title: str=Query(None, title=opasConfig.TITLE_TITLE, description=opasConfig.DESCRIPTION_TITLE),
                             articletype: str=Query(None, title=opasConfig.TITLE_ARTICLETYPE, description=opasConfig.DESCRIPTION_ARTICLETYPE),
                             startyear: str=Query(None, title=opasConfig.TITLE_STARTYEAR, description=opasConfig.DESCRIPTION_STARTYEAR), 
                             endyear: str=Query(None, title=opasConfig.TITLE_ENDYEAR, description=opasConfig.DESCRIPTION_ENDYEAR), 
                             citecount: str=Query(None, title=opasConfig.TITLE_CITECOUNT, description=opasConfig.DESCRIPTION_CITECOUNT),   
                             viewcount: str=Query(None, title=opasConfig.TITLE_VIEWCOUNT, description=opasConfig.DESCRIPTION_VIEWCOUNT),    
                             viewperiod: int=Query(4, title=opasConfig.TITLE_VIEWPERIOD, description=opasConfig.DESCRIPTION_VIEWPERIOD),     
                             # return set control (removed returnFields 2020-09-10)
                             #returnfields: str=Query(None, title="Fields to return (see limitations)", description="Comma separated list of field names"),
                             abstract:bool=Query(False, title="Return an abstract with each match", description="True to return an abstract"),
                             formatrequested: str=Query("HTML", title=opasConfig.TITLE_RETURNFORMATS, description=opasConfig.DESCRIPTION_RETURNFORMATS),
                             similarcount: int=Query(0, title=opasConfig.TITLE_SIMILARCOUNT, description=opasConfig.DESCRIPTION_SIMILARCOUNT),
                             highlightlimit: int=Query(opasConfig.DEFAULT_MAX_KWIC_RETURNS, title=opasConfig.TITLE_MAX_KWIC_COUNT, description=opasConfig.DESCRIPTION_MAX_KWIC_COUNT),
                             facetfields: str=Query(None, title=opasConfig.TITLE_FACETFIELDS, description=opasConfig.DESCRIPTION_FACETFIELDS), 
                             facetmincount: int=Query(1, title="Minimum count to return a facet"),
                             facetlimit: int=Query(15, title="Maximum number of facet values to return"),
                             facetoffset: int=Query(0, title="Offset that can be used for paging through a facet"),
                             sort: str=Query("score desc", title=opasConfig.TITLE_SORT, description=opasConfig.DESCRIPTION_SORT),
                             limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                             offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                             client_id:int=Depends(get_client_id), 
                             client_session:str= Depends(get_client_session)
                             ):
    """
    ## Function
       <b>Search the database per one or more of the fields specified.</b>

       Some of the fields should probably be deprecated, but for now, they support PEP-Easy,
       as configured to use the GVPi based PEP Server
       endyear isn't needed, because startyear can handle the ranges (and better than before).
       journal is also configured to take anything that would have otherwise been entered in sourcename

    ## Return Type
       models.DocumentList

    ## Status
       Status: Working; [potentially this will be deprecated in favor of the post version in the Release Ver.]

       - in perpetual development to extend and improve features
          - smarttext now detects title search under much more restrictive inputs
            due to user input where terrm search was favored
       - Other engines, e.g., disMax, edisMax also not yet implemented


    ## Sample Call
         /v2/Database/Search/?author=Blum&sourcecode=AOP&fulltext1=transference

    ## Notes
          - 2020-09-10 removed returnFields...covered in querySpec for POST version

    ## Limitations

    ## Potential Errors

    """
    ts = time.time()
    opasDocPermissions.verify_header(request, "Search") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)
    #print (f"Call to database_search: SM:{smarttext} FT:{fulltext1} PTXT:{paratext} AU:{author} TI:{title} SY:{startyear} EY:{endyear}")
    errors, mod_args = opasQueryHelper.check_search_args( smarttext=smarttext,
                                                          fulltext1=fulltext1,
                                                          paratext=paratext,
                                                          author=author,
                                                          title=title,
                                                          startyear=startyear,
                                                          endyear=endyear
                                                        )
    if errors:
        detail = "Error 425: Too few characters or unbalanced."
        print(detail)
        raise HTTPException(
            status_code=opasConfig.httpCodes.HTTP_425_TOO_EARLY,
            detail=detail
        )
    
    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    # session_id = session_info.session_id 

    if re.search(r"/Search/", request.url._url):
        logger.debug("Search Request: %s", request.url._url)

    if fulltext1 is not None:
        logger.info("Search Fulltext1: %s", fulltext1)
        
    if smarttext is not None:
        logger.info("Search Smarttext: %s", smarttext)

    analysis_mode = False

    # don't set parascope, unless they set paratext and forgot to set parascope
    if paratext is not None and parascope is None:
        parascope = "doc"

    # current_year = datetime.utcfromtimestamp(time.time()).strftime('%Y')
    # this does intelligent processing of the query parameters and returns a smaller set of solr oriented         
    # params (per pydantic model SolrQuery), ready to use
    solr_query_spec = \
        opasQueryHelper.parse_search_query_parameters(solrQueryTermList=None,
                                                      source_name=sourcename,
                                                      source_code=sourcecode,
                                                      source_type=sourcetype,
                                                      source_lang_code=sourcelangcode,
                                                      para_textsearch=mod_args.get("paratext", None), # search within paragraphs
                                                      para_scope=parascope, # scope for par_search
                                                      similar_count=similarcount, # Turn on morelikethis for the search, return this many similar docs for each
                                                      fulltext1=mod_args.get("fulltext1", None),  # more flexible search, including fields, anywhere in the doc, across paras
                                                      smarttext=mod_args.get("smarttext", None), # experimental detection of what user wants to query
                                                      synonyms=synonyms, 
                                                      vol=volume,
                                                      issue=issue,
                                                      author=author,
                                                      title=title,
                                                      articletype=articletype, 
                                                      startyear=startyear,
                                                      endyear=endyear,
                                                      citecount=citecount,
                                                      viewcount=viewcount,
                                                      highlightlimit=highlightlimit, 
                                                      viewperiod=viewperiod,
                                                      facetfields=facetfields,
                                                      facetmincount=facetmincount,
                                                      facetlimit=facetlimit,
                                                      facetoffset=facetoffset,                                                        
                                                      abstract_requested=abstract,
                                                      formatrequested=formatrequested, 
                                                      limit=limit,
                                                      offset=offset,
                                                      sort=sort,
                                                      req_url = request.url._url
                                                      )

    ret_val, ret_status = search_text_qs(solr_query_spec, 
                                         extra_context_len=opasConfig.DEFAULT_KWIC_CONTENT_LENGTH,
                                         limit=limit,
                                         offset=offset,
                                         session_info=session_info
                                         )

    #  if there's a Solr server error in the call, it returns a non-200 ret_status[0]
    if ret_status[0] != httpCodes.HTTP_200_OK:
        #  throw an exception rather than return an object (which will fail)
        try:
            detail=f"Bad Solr Search Request. {ret_status[1].reason}:{ret_status[1].body}"
        except:
            detail = "Bad Solr Search Request"
            
        raise HTTPException(
            status_code=ret_status[0],
            detail=detail
        )

    if ret_val != {}:
        matches = len(ret_val.documentList.responseSet)
        # ret_val.documentList.responseInfo.request = request.url._url
    else:
        matches = 0

    logger.debug(f"....matches = {matches}")
    # fill in additional return structure status info
    statusMsg = f"{matches} hits; similar documents per result requested:{similarcount}; queryAnalysis: {analysis_mode}"
    logger.debug("Done with search.")

    #try:
        #item_of_interest = None
        #try:
            #fq = re.sub("art_level:1(\s\&\&\s)?", "", solr_query_spec.solrQuery.filterQ, re.I)
            #if fq != '':
                #item_of_interest = f"f:'{fq}'"
                #spacer = " "
            #else:
                #item_of_interest = ""
                #spacer = ""
        #except:
            #fq = ""
            #item_of_interest = ""
            #spacer = ""

        #try:
            #q = re.sub("\*:\*|{!parent\swhich=\'art_level:1\'}\sart_level:2\s&&\s", "", solr_query_spec.solrQuery.searchQ, re.I)
            #if q != '':
                #col_width_remaining = opasConfig.DB_ITEM_OF_INTEREST_WIDTH - len(fq) # don't exceed column width for logging 
                #item_of_interest += f"{spacer}q:'{q[:col_width_remaining]}'"
        #except Exception as e:
            #pass
    #except:
        #item_of_interest = None

    # client_host = request.client.host
    item_of_interest = opasAPISupportLib.get_query_item_of_interest(solrQuery=solr_query_spec.solrQuery)
    
    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_SEARCH,
                                session_info=session_info,
                                item_of_interest=item_of_interest, 
                                params=request.url._url,
                                return_status_code = ret_status[0], 
                                status_message=statusMsg
                                )

    log_endpoint_time(request, ts=ts)
    return ret_val

#---------------------------------------------------------------------------------------------------------
@app.get("/v2/Database/SearchAnalysis/", response_model=models.TermIndex, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_SEARCH_ANALYSIS)  #  remove validation response_model=models.DocumentList, 
def database_searchanalysis_v2(response: Response, 
                               request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                               fulltext1: str=Query(None, title=opasConfig.TITLE_FULLTEXT1, description=opasConfig.DESCRIPTION_FULLTEXT1),
                               smarttext: str=Query(None, title=opasConfig.TITLE_SMARTSEARCH, description=opasConfig.DESCRIPTION_SMARTSEARCH),
                               paratext: str=Query(None, title=opasConfig.TITLE_PARATEXT, description=opasConfig.DESCRIPTION_PARATEXT),
                               parascope: str=Query(None, title=opasConfig.TITLE_PARASCOPE, description=opasConfig.DESCRIPTION_PARASCOPE),
                               synonyms: bool=Query(False, title=opasConfig.TITLE_SYNONYMS_BOOLEAN, description=opasConfig.DESCRIPTION_SYNONYMS_BOOLEAN),
                               # filters (Solr query filter)
                               sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME, min_length=2),  
                               sourcecode: str=Query(None, title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE, min_length=2),
                               sourcelangcode: str=Query(None, title=opasConfig.TITLE_SOURCELANGCODE, description=opasConfig.DESCRIPTION_SOURCELANGCODE), 
                               volume: str=Query(None, title=opasConfig.TITLE_VOLUMENUMBER, description=opasConfig.DESCRIPTION_VOLUMENUMBER), 
                               issue: str=Query(None, title=opasConfig.TITLE_ISSUE, description=opasConfig.DESCRIPTION_ISSUE),
                               author: str=Query(None, title=opasConfig.TITLE_AUTHOR, description=opasConfig.DESCRIPTION_AUTHOR), 
                               title: str=Query(None, title=opasConfig.TITLE_TITLE, description=opasConfig.DESCRIPTION_TITLE),
                               articletype: str=Query(None, title=opasConfig.TITLE_ARTICLETYPE, description=opasConfig.DESCRIPTION_ARTICLETYPE),
                               startyear: str=Query(None, title=opasConfig.TITLE_STARTYEAR, description=opasConfig.DESCRIPTION_STARTYEAR), 
                               endyear: str=Query(None, title=opasConfig.TITLE_ENDYEAR, description=opasConfig.DESCRIPTION_ENDYEAR), 
                               citecount: str=Query(None, title=opasConfig.TITLE_CITECOUNT, description=opasConfig.DESCRIPTION_CITECOUNT),   
                               viewcount: str=Query(None, title=opasConfig.TITLE_VIEWCOUNT, description=opasConfig.DESCRIPTION_VIEWCOUNT),    
                               viewperiod: int=Query(4, title=opasConfig.TITLE_VIEWPERIOD, description=opasConfig.DESCRIPTION_VIEWPERIOD),     
                               # return set control
                               facetfields: str=Query(None, title=opasConfig.TITLE_FACETFIELDS, description=opasConfig.DESCRIPTION_FACETFIELDS), 
                               sort: str=Query("score desc", title=opasConfig.TITLE_SORT, description=opasConfig.DESCRIPTION_SORT),
                               limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                               offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                               #client_id:int=Depends(get_client_id), 
                               #client_session:str= Depends(get_client_session)
                               ):
    """
    ## Function
       <b>Mirror function to search to request an analysis of the search parameters.</b>

    ## Return Type
       models.TermIndex (for v2)

    ## Status
       Status: Working, but in perpetual development to improve

    ## Sample Call

    ## Notes
       6/2020 - The returnfields parameter was removed as not useful here.

    ## Limitations

    ## Potential Errors

    """

    # don't set parascope, unless they set paratext and forgot to set parascope
    if paratext is not None and parascope is None:
        parascope = "doc"

    errors, mod_args = opasQueryHelper.check_search_args(
                                             smarttext=smarttext,
                                             fulltext1=fulltext1,
                                             paratext=paratext,
                                             author=author,
                                             title=title,
                                             startyear=startyear,
                                             endyear=endyear
                                           )
    if errors:
        detail = "Error 425: Too few characters or unbalanced."
        print(detail)
        raise HTTPException(
            status_code=opasConfig.httpCodes.HTTP_425_TOO_EARLY,
            detail=detail
        )
    
    # this does intelligent processing of the query parameters and returns a smaller set of solr oriented         
    # params (per pydantic model SolrQuery), ready to use
    solr_query_spec = \
        opasQueryHelper.parse_search_query_parameters(solrQueryTermList=None,
                                                      source_name=sourcename,
                                                      source_code=sourcecode,
                                                      source_lang_code=sourcelangcode, 
                                                      para_textsearch=mod_args.get("paratext", None), # search within paragraphs
                                                      para_scope=parascope, # scope for par_search
                                                      fulltext1=mod_args.get("fulltext1", None),  # more flexible search, including fields, anywhere in the doc, across paras
                                                      smarttext=mod_args.get("smarttext", None), # experimental detection of what user wants to query
                                                      synonyms=synonyms, 
                                                      vol=volume,
                                                      issue=issue,
                                                      author=author,
                                                      title=title,
                                                      articletype=articletype, 
                                                      startyear=startyear,
                                                      endyear=endyear,
                                                      citecount=citecount,
                                                      viewcount=viewcount,
                                                      viewperiod=viewperiod,
                                                      facetfields=facetfields, 
                                                      sort = sort,
                                                      req_url = request.url._url
                                                      )

    solr_query_spec.urlRequest = request.url._url
    solr_query_params = solr_query_spec.solrQuery

    # We don't always need full-text, but if we need to request the doc later we'll need to repeat the search parameters plus the docID
    ret_val = opasPySolrLib.search_analysis(query_list=solr_query_params.searchAnalysisTermList, 
                                            filter_query = solr_query_params.filterQ,
                                            def_type = "lucene",
                                            #query_analysis=analysis_mode,
                                            #more_like_these = None,
                                            full_text_requested=False,
                                            limit=limit, 
                                            api_version="v2"
                                            )

    logger.debug("Done with search analysis.")
    # print (f"Search analysis called: {solr_query_params}")

    return ret_val

#---------------------------------------------------------------------------------------------------------
@app.post("/v2/Database/SearchAnalysis/", response_model=models.TermIndex, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_SEARCH_ANALYSIS)  #  remove validation response_model=models.DocumentList, 
def database_searchanalysis_v3(response: Response, 
                               request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                               qtermlist: models.SolrQueryTermList=Body(None, embed=True, title=opasConfig.TITLE_QTERMLIST, decription=opasConfig.DESCRIPTION_QTERMLIST), # allows full specification
                               fulltext1: str=Query(None, title=opasConfig.TITLE_FULLTEXT1, description=opasConfig.DESCRIPTION_FULLTEXT1),
                               smarttext: str=Query(None, title=opasConfig.TITLE_SMARTSEARCH, description=opasConfig.DESCRIPTION_SMARTSEARCH),
                               paratext: str=Query(None, title=opasConfig.TITLE_PARATEXT, description=opasConfig.DESCRIPTION_PARATEXT),
                               parascope: str=Query(None, title=opasConfig.TITLE_PARASCOPE, description=opasConfig.DESCRIPTION_PARASCOPE),
                               synonyms: bool=Query(False, title=opasConfig.TITLE_SYNONYMS_BOOLEAN, description=opasConfig.DESCRIPTION_SYNONYMS_BOOLEAN),
                               # filters (Solr query filter)
                               sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME, min_length=2),  
                               sourcecode: str=Query(None, title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE, min_length=2),
                               sourcelangcode: str=Query(None, title=opasConfig.TITLE_SOURCELANGCODE, description=opasConfig.DESCRIPTION_SOURCELANGCODE), 
                               volume: str=Query(None, title=opasConfig.TITLE_VOLUMENUMBER, description=opasConfig.DESCRIPTION_VOLUMENUMBER), 
                               issue: str=Query(None, title=opasConfig.TITLE_ISSUE, description=opasConfig.DESCRIPTION_ISSUE),
                               author: str=Query(None, title=opasConfig.TITLE_AUTHOR, description=opasConfig.DESCRIPTION_AUTHOR), 
                               title: str=Query(None, title=opasConfig.TITLE_TITLE, description=opasConfig.DESCRIPTION_TITLE),
                               articletype: str=Query(None, title=opasConfig.TITLE_ARTICLETYPE, description=opasConfig.DESCRIPTION_ARTICLETYPE),
                               startyear: str=Query(None, title=opasConfig.TITLE_STARTYEAR, description=opasConfig.DESCRIPTION_STARTYEAR), 
                               endyear: str=Query(None, title=opasConfig.TITLE_ENDYEAR, description=opasConfig.DESCRIPTION_ENDYEAR), 
                               citecount: str=Query(None, title=opasConfig.TITLE_CITECOUNT, description=opasConfig.DESCRIPTION_CITECOUNT),   
                               viewcount: str=Query(None, title=opasConfig.TITLE_VIEWCOUNT, description=opasConfig.DESCRIPTION_VIEWCOUNT),    
                               viewperiod: int=Query(4, title=opasConfig.TITLE_VIEWPERIOD, description=opasConfig.DESCRIPTION_VIEWPERIOD),     
                               # return set control
                               facetfields: str=Query(None, title=opasConfig.TITLE_FACETFIELDS, description=opasConfig.DESCRIPTION_FACETFIELDS), 
                               sort: str=Query("score desc", title=opasConfig.TITLE_SORT, description=opasConfig.DESCRIPTION_SORT),
                               limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                               offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                               client_id:int=Depends(get_client_id), 
                               #client_session:str= Depends(get_client_session)
                               ):
    """
    ## Function
       <b>Mirror function to search to request an analysis of the search parameters.</b>

    ## Return Type
       models.TermIndex

    ## Status
       Status: Working, but in perpetual development to improve

    ## Sample Call

    ## Notes
       6/2020 - The returnfields parameter was removed as not useful here.

    ## Limitations

    ## Potential Errors

    """

    ts = time.time()

    # for debugging client call
    #opasDocPermissions.verify_header(request, "SearchAnalysis")
    log_endpoint(request, client_id=client_id)

    # don't set parascope, unless they set paratext and forgot to set parascope
    if paratext is not None and parascope is None:
        parascope = "doc"

    errors, mod_args = opasQueryHelper.check_search_args(
                                             smarttext=smarttext,
                                             fulltext1=fulltext1,
                                             paratext=paratext,
                                             author=author,
                                             title=title,
                                             startyear=startyear,
                                             endyear=endyear
                                           )
    if errors:
        detail = "Error 425: Too few characters or unbalanced."
        print(detail)
        raise HTTPException(
            status_code=opasConfig.httpCodes.HTTP_425_TOO_EARLY,
            detail=detail
        )

    # this does intelligent processing of the query parameters and returns a smaller set of solr oriented         
    # params (per pydantic model SolrQuery), ready to use
    solr_query_spec = \
        opasQueryHelper.parse_search_query_parameters(solrQueryTermList=qtermlist,
                                                      source_name=sourcename,
                                                      source_code=sourcecode,
                                                      source_lang_code=sourcelangcode, 
                                                      para_textsearch=mod_args.get("paratext", None), # search within paragraphs
                                                      para_scope=parascope, # scope for par_search
                                                      fulltext1=mod_args.get("fulltext1", None),  # more flexible search, including fields, anywhere in the doc, across paras
                                                      smarttext=mod_args.get("smarttext", None), # experimental detection of what user wants to query
                                                      synonyms=synonyms, 
                                                      vol=volume,
                                                      issue=issue,
                                                      author=author,
                                                      title=title,
                                                      articletype=articletype, 
                                                      startyear=startyear,
                                                      endyear=endyear,
                                                      citecount=citecount,
                                                      viewcount=viewcount,
                                                      viewperiod=viewperiod,
                                                      facetfields=facetfields, 
                                                      sort = sort,
                                                      req_url = request.url._url
                                                      )

    solr_query_spec.urlRequest = request.url._url
    solr_query_params = solr_query_spec.solrQuery

    # We don't always need full-text, but if we need to request the doc later we'll need to repeat the search parameters plus the docID
    ret_val = opasPySolrLib.search_analysis(query_list=solr_query_params.searchAnalysisTermList, 
                                            filter_query = solr_query_params.filterQ,
                                            def_type = "lucene",
                                            #query_analysis=analysis_mode,
                                            #more_like_these = None,
                                            full_text_requested=False,
                                            limit=limit, 
                                            api_version="v2"
                                            )

    logger.debug("Done with search analysis.")
    # print (f"Search analysis called: {solr_query_params}")
    log_endpoint_time(request, ts=ts)
    return ret_val  # models.Termindex (for v2)
#---------------------------------------------------------------------------------------------------------
@app.get("/v2/Database/SmartSearch/", response_model_exclude_unset=True, tags=["Database", "In Development"]) 
async def database_smartsearch(response: Response, 
                               request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                               smarttext: str=Query(None, title=opasConfig.TITLE_SMARTSEARCH, description=opasConfig.DESCRIPTION_SMARTSEARCH),
                               # filters, v1 naming
                               sort: str=Query("score desc", title=opasConfig.TITLE_SORT, description=opasConfig.DESCRIPTION_SORT),
                               abstract:bool=Query(False, title="Return an abstract with each match", description="True to return an abstract"),
                               similarcount: int=Query(0, title=opasConfig.TITLE_SIMILARCOUNT, description=opasConfig.DESCRIPTION_SIMILARCOUNT),
                               formatrequested: str=Query("HTML", title=opasConfig.TITLE_RETURNFORMATS, description=opasConfig.DESCRIPTION_RETURNFORMATS),
                               highlightlimit: int=Query(opasConfig.DEFAULT_MAX_KWIC_RETURNS, title=opasConfig.TITLE_MAX_KWIC_COUNT, description=opasConfig.DESCRIPTION_MAX_KWIC_COUNT),
                               facetfields: str=Query(None, title=opasConfig.TITLE_FACETFIELDS, description=opasConfig.DESCRIPTION_FACETFIELDS), 
                               limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                               offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                               client_id:int=Depends(get_client_id), 
                               client_session:str= Depends(get_client_session)
                               ):
    """
    ## Function

    Convenience function for testing the smarttext searching (smartsearch).  With fewer parameters, it's easier to
    test and experiment with in the OpenAPI interface.  The results would be the same calling the Search endpoint and providing the
    same argument to smarttext, but if this is all you need, use it directly.

    Also, this endpoint provides an easier way to isolate and document the types of calls interpreted by smarttext.

    ## Return Type
       models.DocumentList

    ## Status
       Status: Working, but in perpetual development to improve

    ## Sample Call

    Below, here are some values and the style you can submit in parameter smarttext.  To see what they
    are interpreted to in Solr syntax, see the scopeQuery field of ResponseInfo in the response, where the first
    value is Solr q and the second is fq.

    "scopeQuery": [

        [
          "*:*",

          "art_id:(NLP.001.0001A)"

        ]

    1a) Author Names and dates (best detection to use standard form, parentheses around the date.)
        Last names should be initial capitalized without first initials, e.g.,

       Shapiro, Shapiro, Zinner and Berkowitz (1977)   --> 1 hit

       Tuckett and Fonagy 2012                         --> 1 hit

       Kohut, H. & Wolf, E. S. (1978)                  --> 1 hit

    1b) Author names without dates, e.g.,

       Shapiro, Shapiro, Zinner and Berkowitz          --> 3 hits

    2) Special IDs

    2a) DOIs, e.g., (all 1 hit each)

        10.1111/j.1745-8315.2012.00606.x

        10.3280/PU2019-004002

    2b) PEP Locators (IDs)

        AOP.033.0079A

        PEP/AOP.033.0079A


    2) Search any schema field, use Solr type notation, but one schema field per entry. 
    art_type: ART or COM


    ## Notes

    ## Potential Errors

    """
    opasDocPermissions.verify_header(request, "SmartSearch") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ret_val = await database_search_v2(response,
                                       request,
                                       fulltext1=None,
                                       paratext=None, 
                                       parascope=None,
                                       smarttext=smarttext, 
                                       synonyms=False,
                                       similarcount=similarcount, 
                                       sourcecode=None,
                                       sourcename=None, 
                                       sourcetype=None, 
                                       sourcelangcode=None, 
                                       volume=None,
                                       issue=None, 
                                       author=None,
                                       title=None,
                                       articletype=None, 
                                       startyear=None,
                                       endyear=None, 
                                       citecount=None,   
                                       viewcount=None,   
                                       viewperiod=None,
                                       highlightlimit=highlightlimit, 
                                       facetfields=facetfields,
                                       facetmincount=1,
                                       facetlimit=15,
                                       facetoffset=0,
                                       abstract=abstract,
                                       sort=sort,
                                       formatrequested=formatrequested, 
                                       limit=limit,
                                       offset=offset,
                                       client_id=client_id,
                                       client_session=client_session
                                       )
    return ret_val

#---------------------------------------------------------------------------------------------------------
#@app.get("/v1/Database/MostDownloaded/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Deprecated"], summary=opasConfig.ENDPOINT_SUMMARY_MOST_VIEWED)
@app.get("/v2/Database/MostViewed/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_MOST_VIEWED)
def database_mostviewed(response: Response,
                        request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                        # period is str because it can be "all"
                        pubperiod: int=Query(None, title=opasConfig.TITLE_PUBLICATION_PERIOD, description=opasConfig.DESCRIPTION_PUBLICATION_PERIOD),
                        # viewperiod=4 for last 12 months
                        viewperiod: int=Query(4, title=opasConfig.TITLE_MOST_VIEWED_PERIOD, description=opasConfig.DESCRIPTION_MOST_VIEWED_PERIOD), # 4=Prior year, per PEP-Web design
                        viewcount: int=Query(None, title=opasConfig.TITLE_VIEWCOUNT, description=opasConfig.DESCRIPTION_VIEWCOUNT_INT),
                        author: str=Query(None, title=opasConfig.TITLE_AUTHOR, description=opasConfig.DESCRIPTION_AUTHOR), 
                        title: str=Query(None, title=opasConfig.TITLE_TITLE, description=opasConfig.DESCRIPTION_TITLE),
                        sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME),  
                        sourcecode: str=Query(None, title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE), 
                        sourcetype: str=Query("journal", title=opasConfig.TITLE_SOURCETYPE, description=opasConfig.DESCRIPTION_PARAM_SOURCETYPE),
                        abstract:bool=Query(False, title=opasConfig.TITLE_RETURN_ABSTRACTS_BOOLEAN, description=opasConfig.DESCRIPTION_RETURN_ABSTRACTS),
                        similarcount: int=Query(0, title=opasConfig.TITLE_SIMILARCOUNT, description=opasConfig.DESCRIPTION_SIMILARCOUNT),
                        stat:bool=Query(False, title=opasConfig.TITLE_STATONLY, description=opasConfig.DESCRIPTION_STATONLY),
                        limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT), # by PEP-Web standards, we want 10, but 5 is better for PEP-Easy
                        offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                        download:bool=Query(False, title=opasConfig.TITLE_DOWNLOAD, description=opasConfig.DESCRIPTION_DOWNLOAD), 
                        client_id:int=Depends(get_client_id), 
                        client_session:str=Depends(get_client_session)
                        ):
    """
    ## Function
       <b>Return a list of documents which are the most downloaded (viewed)</b>

            viewperiod = 0: lastcalendaryear
                         1: lastweek
                         2: lastmonth
                         3: last6months
                         4: last12months                                

    ## Return Type
       models.DocumentList (or returns response if a download is requested )

    ## Status
       This endpoint is working.
       For whatever reason, async works here, without a wait on the long running database call.  And
         adding the await makes it never return

    ## Sample Call
         /v2/Database/MostViewed/

    ## Notes

    ## Potential Errors

    """
    ts = time.time()
    ret_val = None
    query_arg_error = None
    
    opasDocPermissions.verify_header(request, "MostViewed") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    if viewperiod < 0 or viewperiod > 4:
        query_arg_error = f"Most Viewed: viewperiod: {viewperiod}.  Range should be 0-4 (int)."

    if sourcetype is not None: # none is ok
        sourcetype = opasConfig.normalize_val(sourcetype, opasConfig.VALS_SOURCE_TYPE, None)
        if sourcetype is None: # trap error on None, default
            query_arg_error = opasConfig.norm_val_error(opasConfig.VALS_SOURCE_TYPE, "Most Viewed: sourcetype")

    # exit on arg error        
    if query_arg_error is not None:
        status_message = f"Error: {query_arg_error}"
        logger.warning(status_message)
        ret_val = None
        raise HTTPException(
            status_code=httpCodes.HTTP_400_BAD_REQUEST, 
            detail=status_message
        )        

    if download == True:
        # Download CSV of selected set.  Returns only response with download, not usual documentList
        #   response to client
        if limit == opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS:
            limit = None

        views = ocd.most_viewed_generator( publication_period=pubperiod,
                                           view_in_period=viewperiod,
                                           viewcount=viewcount, 
                                           author=author,
                                           title=title,
                                           source_name=sourcename, 
                                           source_code=sourcecode,
                                           source_type=sourcetype,  # see VALS_SOURCE_TYPE (norm_val applied in opasCenralDBLib)
                                           select_clause=opasConfig.VIEW_MOSTVIEWED_DOWNLOAD_COLUMNS, 
                                           limit=limit,
                                           offset=offset,
                                           session_info=session_info
                                           )            
        header = ["Document", "Last Week", "Last Month", "Last 6 Months", "Last 12 Months", "Last Calendar Year"]
        df = pd.DataFrame(views)
        stream = io.StringIO()
        df.to_csv(stream, header=header, index = False)
        response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=pepviews.csv"
        # Don't record endpoint use (not a user request, just a default) but do record download
        status_message = "Success"
        status_code = httpCodes.HTTP_200_OK
        ocd.record_session_endpoint( api_endpoint_id=opasCentralDBLib.API_DATABASE_MOSTVIEWED,
                                     session_info=session_info, 
                                     params=request.url._url,
                                     return_status_code = status_code,
                                     status_message=status_message
                                     )
        ret_val = response

    else: # go ahead! Search Solr
        try:
            # we want the last year (default, per PEP-Web) of views, for all articles (journal articles)
            ret_val, ret_status = opasAPISupportLib.database_get_most_viewed( publication_period=pubperiod,
                                                                              view_period=viewperiod, # limiting to 5, you'd get the 5 biggest values for this view period
                                                                              view_count=viewcount, 
                                                                              author=author,
                                                                              title=title,
                                                                              source_name=sourcename, 
                                                                              source_code=sourcecode,
                                                                              source_type=sourcetype, # see VALS_SOURCE_TYPE (norm_val applied in opasCenralDBLib)
                                                                              abstract_requested=abstract, 
                                                                              req_url=request.url._url,
                                                                              stat=stat, 
                                                                              limit=limit, 
                                                                              offset=offset,
                                                                              download=download, 
                                                                              mlt_count=similarcount, 
                                                                              session_info=session_info
                                                                              )

            if ret_val is None:
                status_message = f"Solr error for request (no return)"
                logger.error(status_message)
                raise HTTPException(
                    status_code=httpCodes.HTTP_400_BAD_REQUEST, 
                    detail=status_message
                )        
                
        except Exception as e:
            ret_val = None
            status_message = f"Error: {e}"
            logger.error(status_message)
            raise HTTPException(
                status_code=httpCodes.HTTP_400_BAD_REQUEST, 
                detail=status_message
            )        
        else:
            if isinstance(ret_val, models.ErrorReturn):
                logger.error("Getmostviewed error return. Raising exception")
                raise HTTPException(
                    status_code=ret_val.httpcode, 
                    detail = ret_val.error + " - " + ret_val.error_description
                )
        
    log_endpoint_time(request, ts=ts)
    return ret_val  # document_list

#---------------------------------------------------------------------------------------------------------
@app.get("/v2/Database/MostCited/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_MOST_CITED)
def database_mostcited(response: Response,
                       request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                       citeperiod: str=Query('5', title=opasConfig.TITLE_MOST_CITED_PERIOD, description=opasConfig.DESCRIPTION_MOST_CITED_PERIOD),
                       citecount: str=Query(None, title=opasConfig.TITLE_CITECOUNT, description=opasConfig.DESCRIPTION_CITECOUNT),   
                       pubperiod: int=Query(None, title=opasConfig.TITLE_PUBLICATION_PERIOD, description=opasConfig.DESCRIPTION_PUBLICATION_PERIOD),
                       author: str=Query(None, title=opasConfig.TITLE_AUTHOR, description=opasConfig.DESCRIPTION_AUTHOR), 
                       title: str=Query(None, title=opasConfig.TITLE_TITLE, description=opasConfig.DESCRIPTION_TITLE),
                       sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME),  
                       sourcecode: str=Query(None, title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE), 
                       sourcetype: str=Query(None, title=opasConfig.TITLE_SOURCETYPE, description=opasConfig.DESCRIPTION_PARAM_SOURCETYPE),
                       abstract:bool=Query(False, title=opasConfig.TITLE_RETURN_ABSTRACTS_BOOLEAN, description=opasConfig.DESCRIPTION_RETURN_ABSTRACTS),
                       similarcount: int=Query(0, title=opasConfig.TITLE_SIMILARCOUNT, description=opasConfig.DESCRIPTION_SIMILARCOUNT),
                       stat:bool=Query(False, title=opasConfig.TITLE_STATONLY, description=opasConfig.DESCRIPTION_STATONLY),
                       limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                       offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                       download:bool=Query(False, title=opasConfig.TITLE_DOWNLOAD, description=opasConfig.DESCRIPTION_DOWNLOAD), 
                       client_id:int=Depends(get_client_id), 
                       client_session:str= Depends(get_client_session)
                       ):
    """
    ## Function
       <b>Return a list of documents for a SourceCode source (and optional year specified in query params).</b>

       If you don't request abstracts returned, document permissions will not be checked or returned.
       This is intended to speed up retrieval, especially for returning large numbers of
       articles (e.g., for downloads.)

       MoreLikeThese, controlled by similarcount, is set to be off by default (0)

       Note: The GVPi implementation does not appear to support the limit and offset parameter


    ## Return Type
       models.DocumentList

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Database/MostCited/

    ## Notes

    ## Potential Errors

    """

    ret_val = True
    ts = time.time()
    
    opasDocPermissions.verify_header(request, "MostCited") # for debugging client call 
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    # session_id = session_info.session_id 

    if download == True:
        # turn off similarity, waste of time
        similarcount = 0
        if limit == opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS:
            limit = 299999 # force no limit!

        # Download CSV of selected set.  Returns only response with download, not usual documentList
        #   response to client
        views = ocd.most_cited_generator( cited_in_period=citeperiod,
                                          citecount=citecount,
                                          publication_period=pubperiod,
                                          author=author,
                                          title=title,
                                          source_name=sourcename, 
                                          source_code=sourcecode,
                                          source_type=sourcetype,  # see VALS_SOURCE_TYPE (norm_val applied in opasCenralDBLib)
                                          select_clause=opasConfig.VIEW_MOSTCITED_DOWNLOAD_COLUMNS, 
                                          limit=limit,
                                          offset=offset
                                          )

        header = ["Document", "Last 5 Years", "Last 10 years", "Last 20 years", "All years"]
        df = pd.DataFrame(views)
        stream = io.StringIO()
        df.to_csv(stream, header=header, index = False)
        response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=pepcited.csv"
        ret_val = response
        # Don't record endpoint use (not a user request, just a default) but do record download
        status_message = "Success"
        status_code = httpCodes.HTTP_200_OK
        ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_MOSTCITED,
                                    session_info=session_info, 
                                    params=request.url._url,
                                    return_status_code = status_code,
                                    status_message=status_message
                                    )

    else:
        # return documentList, much more limited document list if download==True
        ret_val, ret_status = opasAPISupportLib.database_get_most_cited( cited_in_period=citeperiod,
                                                                         cite_count=citecount,
                                                                         publication_period=pubperiod,
                                                                         author=author,
                                                                         title=title,
                                                                         source_name=sourcename, 
                                                                         source_code=sourcecode,
                                                                         source_type=sourcetype,  # see VALS_SOURCE_TYPE (norm_val applied in opasCenralDBLib)
                                                                         abstract_requested=abstract, 
                                                                         req_url=request.url, 
                                                                         limit=limit,
                                                                         offset=offset,
                                                                         download=False, 
                                                                         mlt_count=similarcount, 
                                                                         session_info=session_info
                                                                         )

        if isinstance(ret_val, models.ErrorReturn): 
            logger.error("GetmostCited error return. Raising exception")
            raise HTTPException(
                status_code=ret_val.httpcode, 
                detail = ret_val.error + " - " + ret_val.error_description
            )

        if ret_val is None:
            logger.error("GetmostCited error return. Raising exception")
            raise HTTPException(
                status_code=httpCodes.HTTP_400_BAD_REQUEST, 
                detail = f"Search for MostCited returned None.  Status: {ret_status}"
            )
            
        # Don't record in final build - (ok for now during testing)

    log_endpoint_time(request, ts=ts)
    return ret_val

#---------------------------------------------------------------------------------------------------------
@app.get("/v2/Database/WhoCitedThis/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_WHO_CITED)
def database_who_cited_this(response: Response,
                            request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                            citedid: str=Query(None, title=opasConfig.TITLE_CITED_ID, description=opasConfig.DESCRIPTION_CITEDID), 
                            pubperiod: int=Query(None, title=opasConfig.TITLE_PUBLICATION_PERIOD, description=opasConfig.DESCRIPTION_PUBLICATION_PERIOD),
                            sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME + " of citing document"),  
                            sourcecode: str=Query(None, title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE + " of citing document"), 
                            sourcetype: str=Query(None, title=opasConfig.TITLE_SOURCETYPE, description=opasConfig.DESCRIPTION_PARAM_SOURCETYPE + " of citing document"),
                            abstract:bool=Query(False, title=opasConfig.TITLE_RETURN_ABSTRACTS_BOOLEAN, description=opasConfig.DESCRIPTION_RETURN_ABSTRACTS),
                            similarcount: int=Query(0, title=opasConfig.TITLE_SIMILARCOUNT, description=opasConfig.DESCRIPTION_SIMILARCOUNT),
                            sort: str=Query("score desc", title=opasConfig.TITLE_SORT, description=opasConfig.DESCRIPTION_SORT),
                            limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                            offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                            client_id:int=Depends(get_client_id), 
                            client_session:str= Depends(get_client_session)
                            ):
    """
    ## Function
       <b>Return a list of documents citing the document specified by citedid.</b>

       If you don't request abstracts returned, document permissions will not be checked or returned.
       This is intended to speed up retrieval, especially for returning large numbers of
       articles (e.g., for downloads.)

       MoreLikeThese, controlled by similarcount, is set to be off by default (0)

    ## Return Type
       models.DocumentList

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Database/WhoCitedThis/?citedid=IJP.077.0217A

    ## Notes

    ## Potential Errors

    """

    ret_val = True
    ts = time.time()
    
    opasDocPermissions.verify_header(request, "WhoCitedThis") # for debugging client call    
    log_endpoint(request, client_id=client_id, session_id=client_session)

    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    # session_id = session_info.session_id 

    # return documentList, much more limited document list if download==True
    ret_val, ret_status = opasAPISupportLib.database_who_cited( cited_art_id=citedid,
                                                                publication_period=pubperiod,
                                                                source_name=sourcename, 
                                                                source_code=sourcecode,
                                                                source_type=sourcetype,  # see VALS_SOURCE_TYPE (norm_val applied in opasCenralDBLib)
                                                                abstract_requested=abstract, 
                                                                req_url=request.url,
                                                                sort=sort, 
                                                                limit=limit,
                                                                offset=offset,
                                                                download=False, 
                                                                mlt_count=similarcount, 
                                                                session_info=session_info
                                                                )

    if isinstance(ret_val, models.ErrorReturn): 
        raise HTTPException(
            status_code=ret_val.httpcode, 
            detail = ret_val.error + " - " + ret_val.error_description
        )
    else:
        status_message = opasCentralDBLib.API_STATUS_SUCCESS
        status_code = httpCodes.HTTP_200_OK

    log_endpoint_time(request, ts=ts)
    return ret_val

#---------------------------------------------------------------------------------------------------------
#@app.get("/v1/Database/WhatsNew/", response_model=models.WhatsNewList, response_model_exclude_unset=True, tags=["PEPEasy1 (Deprecated)"], summary=opasConfig.ENDPOINT_SUMMARY_WHATS_NEW)
@app.get("/v2/Database/WhatsNew/", response_model=models.WhatsNewList, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_WHATS_NEW)
def database_whatsnew(response: Response,
                      request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                      days_back: int=Query(14, title=opasConfig.TITLE_DAYSBACK, description=opasConfig.DESCRIPTION_DAYSBACK),
                      limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                      offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                      client_id:int=Depends(get_client_id), 
                            #client_session:str= Depends(get_client_session)
                      ):  
    """
    ## Function
       <b>Return a list of issues for journals modified in the last week).</b>  


    ## Return Type
       models.WhatsNewList

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Database/WhatsNew/

    ## Notes

    ## Potential Errors

    """
    ts = time.time()

    # for debugging client call
    #opasDocPermissions.verify_header(request, "WhatsNew")
    # (Don't log calls to this endpoint)
    # ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    log_endpoint(request, client_id=client_id)
    
    try:
        # return whatsNewList
        ret_val = opasPySolrLib.database_get_whats_new(limit=limit, 
                                                       offset=offset,
                                                       days_back=days_back, 
                                                       req_url=request.url
                                                       )

    except Exception as e:
        e = str(e)
        raise HTTPException(status_code=httpCodes.HTTP_400_BAD_REQUEST,
                            detail="Error: {}".format(e.replace("'", "\\'"))
                            )
    else:
        # response.status_message = "Success"
        response.status_code = httpCodes.HTTP_200_OK
        ret_val.whatsNew.responseInfo.request = request.url._url

    log_endpoint_time(request, ts=ts)
    return ret_val

#-----------------------------------------------------------------------------
#@app.get("/v1/Metadata/Contents/{SourceCode}/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Deprecated"], summary=opasConfig.ENDPOINT_SUMMARY_CONTENTS_SOURCE)
@app.get("/v2/Metadata/Contents/{SourceCode}/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Metadata"], summary=opasConfig.ENDPOINT_SUMMARY_CONTENTS_SOURCE)
def metadata_contents_sourcecode(response: Response,
                                 request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                                 SourceCode: str=Path(..., title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE), 
                                 year: str=Query("*", title=opasConfig.TITLE_YEAR, description=opasConfig.DESCRIPTION_YEAR),
                                 moreinfo:int=Query(0, title="Extra volume info", description="Extra info"), 
                                 limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_CONTENTS_LISTS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                                 offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                                 client_id:int=Depends(get_client_id), 
                                 client_session:str= Depends(get_client_session)
                                 ):
    """
    ## Function
       <b>Return a list of documents for a SourceCode (and optional year specified in query params).</b>  

       Note: The GVPi implementation does not appear to support the limit and offset parameter

    ## Return Type
       models.DocumentList

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Metadata/Contents/IJP/

    ## Notes

    ## Potential Errors

    """
    # ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)
    ts = time.time()
    log_endpoint(request, client_id=client_id)
    
    try:       
        ret_val = opasPySolrLib.metadata_get_contents(SourceCode,
                                                          year,
                                                          extra_info=moreinfo, 
                                                          limit=limit,
                                                          offset=offset)
        # fill in additional return structure status info
        # client_host = request.client.host
    except Exception as e:
        status_message = "Error: {}".format(e)
        raise HTTPException(
            status_code=httpCodes.HTTP_400_BAD_REQUEST,
            detail=status_message
        )
    else:
        status_message = opasCentralDBLib.API_STATUS_SUCCESS
        status_code = httpCodes.HTTP_200_OK
        ret_val.documentList.responseInfo.request = request.url._url

    #ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_METADATA_CONTENTS,
                                #session_info=session_info, 
                                #params=request.url._url,
                                #item_of_interest="{}.{}".format(SourceCode, year), 
                                #return_status_code = status_code,
                                #status_message=status_message
                                #)

    return ret_val # document_list

#-----------------------------------------------------------------------------
#@app.get("/v1/Metadata/Contents/{SourceCode}/{SourceVolume}/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Deprecated"], summary=opasConfig.ENDPOINT_SUMMARY_CONTENTS_SOURCE_VOLUME)
@app.get("/v2/Metadata/Contents/{SourceCode}/{SourceVolume}/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Metadata"], summary=opasConfig.ENDPOINT_SUMMARY_CONTENTS_SOURCE_VOLUME)
def metadata_contents(SourceCode: str, 
                      SourceVolume: str, 
                      response: Response,
                      request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                      year: str=Query("*", title=opasConfig.TITLE_YEAR, description=opasConfig.DESCRIPTION_YEAR),
                      moreinfo:int=Query(0, title="Extra volume info", description="Extra info"), 
                      limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_CONTENTS_LISTS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                      offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                      client_id:int=Depends(get_client_id), 
                      client_session:str= Depends(get_client_session)
                      ):
    """
    ## Function
       <b>Return a list of documents for a SourceCode and Source Volume (required).</b>  

       Year can also be optionally specified in query params.  

    ## Return Type
       models.DocumentList

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Metadata/Contents/IJP/77/
         http://development.org:9100/v2/Metadata/Contents/IJP/77/

    ## Notes

    ## Potential Errors

    """
    # ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)
    log_endpoint(request, client_id=client_id)

    try:
        ret_val = documentList = opasPySolrLib.metadata_get_contents(SourceCode,
                                                                         year,
                                                                         vol=SourceVolume,
                                                                         extra_info=moreinfo, 
                                                                         limit=limit,
                                                                         offset=offset)
        # fill in additional return structure status info
        # client_host = request.client.host
    except Exception as e:
        status_message = "Error: {}".format(e)
        logger.error(status_message)
        raise HTTPException(
            status_code=httpCodes.HTTP_400_BAD_REQUEST,
            detail=status_message
        )
    else:
        status_message = opasCentralDBLib.API_STATUS_SUCCESS
        status_code = httpCodes.HTTP_200_OK
        ret_val.documentList.responseInfo.request = request.url._url

    # 2020-07-23 No need to log success for these, can be excessive.
    #ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_METADATA_CONTENTS_FOR_VOL,
                                #session_info=session_info, 
                                #item_of_interest="{}.{}".format(SourceCode, SourceVolume), 
                                #params=request.url._url,
                                #return_status_code = status_code,
                                #status_message=status_message
                                #)
    return ret_val

#-----------------------------------------------------------------------------
#@app.get("/v1/Metadata/Videos/", response_model=models.VideoInfoList, response_model_exclude_unset=True, tags=["PEPEasy1 (Deprecated)"], summary=opasConfig.ENDPOINT_SUMMARY_VIDEOS)
@app.get("/v2/Metadata/Videos/", response_model=models.VideoInfoList, response_model_exclude_unset=True, tags=["Metadata"], summary=opasConfig.ENDPOINT_SUMMARY_VIDEOS)
def metadata_videos(response: Response,
                    request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                    sourcecode: str=Query("*", title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE_METADATA_VIDEOS),
                    sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME),
                    streams: bool=Query(True, description="Return videostreams (e.g., by publisher) rather than individual video information"),
                    limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_METADATA_LISTS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                    offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                    client_id:int=Depends(get_client_id), 
                    client_session:str= Depends(get_client_session)
                    ):
    """
    ## Function
    <b>Get a complete list of video names</b>

    Query parameter sourcecode is the short abbreviation of the videostream (by publisher) used as part of the DocumentIDs. (e.g., for PEP in 2020, this includes:
      IPSAVS, PEPVS, PEPTOPAUTHVS, BPSIVS, IJPVS, PCVS, SFCPVS, UCLVS, PEPGRANTVS, AFCVS, NYPSIVS, SPIVS).
      
    To get information on all, do not specify a sourcecode (* is the default)
    
    To get 

    ## Return Type
       models.VideoInfoList

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Metadata/Videos/

    ## Notes

    ## Potential Errors

    """
    if streams:
        source_type = "stream"
    else:
        source_type = "videos"
    
    ret_val = metadata_by_sourcetype_sourcecode(response,
                                                request,
                                                SourceType=source_type,
                                                SourceCode=sourcecode,
                                                sourcename=sourcename, 
                                                limit=limit,
                                                offset=offset,
                                                client_id=client_id, 
                                                client_session= client_session
                                                )
    return ret_val

#-----------------------------------------------------------------------------
@app.get("/v2/Metadata/Journals/", response_model=models.JournalInfoList, response_model_exclude_unset=True, tags=["Metadata"], summary=opasConfig.ENDPOINT_SUMMARY_JOURNALS)
def metadata_journals(response: Response,
                      request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                      #this param changed to sourcecode in v2 from journal in v1 (sourcecode is more accurately descriptive since this includes book series and video series)
                      sourcecode: str=Query("*", title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE_METADATA_JOURNALS), 
                      sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME),  
                      limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_METADATA_LISTS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                      offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                      client_id:int=Depends(get_client_id), 
                      client_session:str= Depends(get_client_session)
                      ):
    """
    ## Function
    <b>Get a list of of journal names and metadata equivalent to what is displayed on the original PEP-Web in the journals tab.</b>
    
    To get information on a specific journal, set the sourcecode query parameter to one of the standard PEP journal
    codes (the first part of the three part document ID for articles (e.g., AJRPP, IJP, PAQ).  Case is not treated signficantly.
    
    ## Return Type
       models.JournalInfoList (return label sourceInfo)

    ## Status
       This endpoint is working.

    ## Sample Call
       /v2/Metadata/Journals/

    ## Notes

    ## Potential Errors

    """
    log_endpoint(request, client_id=client_id)
    ret_val = metadata_by_sourcetype_sourcecode(response,
                                                request,
                                                SourceType="Journal",
                                                SourceCode=sourcecode,
                                                sourcename=sourcename, 
                                                limit=limit,
                                                offset=offset,
                                                client_id=client_id
                                                #client_session= client_session
                                                )
    return ret_val

#-----------------------------------------------------------------------------
@app.get("/v2/Metadata/Volumes/", response_model=models.VolumeList, response_model_exclude_unset=True, tags=["Metadata"], summary=opasConfig.ENDPOINT_SUMMARY_VOLUMES)
def metadata_volumes(response: Response,
                     request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                     sourcetype: str=Query(None, title=opasConfig.TITLE_SOURCETYPE, description=opasConfig.DESCRIPTION_PARAM_SOURCETYPE),
                     sourcecode: str=Query(None, title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE), 
                     #limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_VOLUME_LISTS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                     #offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                     client_id:int=Depends(get_client_id), 
                           #client_session:str= Depends(get_client_session)
                     ):
    """
    ## Function
       <b>Return a list of volumes for a SourceCode (aka, PEPCode (e.g., IJP)) per the limit and offset parameters</b> 

    ## Return Type
       models.JournalInfoList

    ## Status
       This endpoint is working.

    ## Sample Call
         {url}/v2/Metadata/Volumes/?sourcecode=ijp

    ## Notes
      2020.11.17 Removed limit and offset from q params: they don't work here with the facet pivot used,
                 and moreover, don't make sense when you have more than one journal being returned

    ## Potential Errors

    """
    ocd = opasCentralDBLib.opasCentralDB()
    log_endpoint(request, client_id=client_id)

    # Solr is case sensitive, make sure arg is upper
    try:
        source_code = sourcecode.upper()
    except:
        source_code = None

    src_exists = ocd.get_sources(src_code=source_code)
    if not src_exists[0] and source_code != "*" and source_code not in ["ZBK", "NLP", "IPL"] and source_code is not None: # ZBK not in productbase table without booknum
        response.status_code = httpCodes.HTTP_400_BAD_REQUEST
        status_message = f"Failure: Bad SourceCode {source_code}"
        raise HTTPException(
            status_code=response.status_code,
            detail=status_message
        )
    else:
        try:
            ret_val = opasPySolrLib.metadata_get_volumes(source_code,
                                                         source_type=sourcetype,
                                                         req_url=request.url
                                                         #limit=limit,   # these don't work with facet pivot used here
                                                         #offset=offset  # at least with solrpy
                                                         )
        except Exception as e:
            response.status_code = httpCodes.HTTP_400_BAD_REQUEST,
            status_message = "Error: {}".format(e)
            raise HTTPException(
                status_code=response.status_code, 
                detail=status_message
            )
        else:
            response.status_code = httpCodes.HTTP_200_OK
            status_message = opasCentralDBLib.API_STATUS_SUCCESS

    return ret_val # returns volumeList

#-----------------------------------------------------------------------------
#@app.get("/v1/Metadata/Books/", response_model=models.SourceInfoList, response_model_exclude_unset=True, tags=["PEPEasy1 (Deprecated)"], summary=opasConfig.ENDPOINT_SUMMARY_BOOK_NAMES)
@app.get("/v2/Metadata/Books/", response_model=models.SourceInfoList, response_model_exclude_unset=True, tags=["Metadata"], summary=opasConfig.ENDPOINT_SUMMARY_BOOK_NAMES)
def metadata_books(response: Response,
                   request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                   sourcecode: str=Query("*", title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE_METADATA_BOOKS), 
                   sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME),  
                   limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_METADATA_LISTS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                   offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                   client_id:int=Depends(get_client_id), 
                         #client_session:str= Depends(get_client_session)
                   ):
    """
    ## Function
       <b>Get a list of Book names equivalent to what is displayed on the original PEP-Web in the books tab.</b>

       The data is pulled from the database ISSN table.  Subvolumes of a book series (e.g., GW, SE) are not returned, nor is any volume
       marked with multivolumesubbok in the src_type_qualifier column.  This is exactly what's currently in PEP-Web's
       presentation today.
       
       To get metadata for a specific book of a series or subvolume of a multivolume book like GW, SE, NLP, IPL, or ZBK,
       use the first two parts of the source document ID (series and series volume) without the period separator used in
       the document ID. For example, to request metadata for SE volume 6, use SE006 in the sourcecode API parameter.
       Similarly, use NLP014 to get metadata on the book published as volume 14 of the NLP series.  While ZBK is a general
       series ID for classic books, the same is true...use ZBK047 to return metadata on that specific book.

    ## Return Type
       models.SourceInfoList (return label sourceInfo)

    ## Status
       This endpoint is working.

    ## Sample Call
         {url}/v2/Metadata/Books/?sourcecode=SE

    ## Notes

    ## Potential Errors

    """

    ret_val = metadata_by_sourcetype_sourcecode(response,
                                                request,
                                                SourceType="Book",
                                                SourceCode=sourcecode,
                                                sourcename=sourcename, 
                                                limit=limit,
                                                offset=offset,
                                                client_id=client_id 
                                                #client_session=client_session
                                                )
    return ret_val

#-----------------------------------------------------------------------------
#@app.get("/v1/Metadata/{SourceType}/{SourceCode}/", response_model=models.SourceInfoList, response_model_exclude_unset=True, tags=["Deprecated"], summary=opasConfig.ENDPOINT_SUMMARY_SOURCE_NAMES)
@app.get("/v1/Metadata/{SourceType}/{SourceCode}/", response_model=models.SourceInfoList, response_model_exclude_unset=True, tags=["Metadata"], summary=opasConfig.ENDPOINT_SUMMARY_SOURCE_NAMES)
def metadata_by_sourcetype_sourcecode(response: Response,
                                      request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                                      SourceType: str=Path(..., title=opasConfig.TITLE_SOURCETYPE, description=opasConfig.DESCRIPTION_PATH_SOURCETYPE), 
                                      SourceCode: str=Path(..., title=opasConfig.TITLE_SOURCECODE, description=opasConfig.DESCRIPTION_SOURCECODE), 
                                      sourcename: str=Query(None, title=opasConfig.TITLE_SOURCENAME, description=opasConfig.DESCRIPTION_SOURCENAME),  
                                      limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_METADATA_LISTS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                                      offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                                      client_id:int=Depends(get_client_id), 
                                      client_session:str= Depends(get_client_session)
                                      ):
    """

    ## Function
       <b>Return a list of information about a source type, e.g., journal names</b>

       The data is pulled from the database ISSN table.  Subvolumes, of SE and GW are not returned, nor is any volume
       marked with multivolumesubbok in the src_type_qualifier column.  This is exactly what's currently in PEP-Web's
       presentation today.

    ## Return Type
       models.SourceInfoList

    ## Status
       This endpoint is working.

    ## Sample Call
         http://localhost:9100/v2/Metadata/Books/IPL

    ## Notes
       Depends on:
          vw_api_productbase for videos

    ## Potential Errors


    """
    opasDocPermissions.verify_header(request, "metadata_by_sourcetype_sourcecode") # for debugging client call
    log_endpoint(request, client_id=client_id)

    #ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    source_code = SourceCode.upper()
    try:    
        ret_val = source_info_list = opasAPISupportLib.metadata_get_source_info(src_type=SourceType,
                                                                                src_code=source_code,
                                                                                src_name=sourcename, 
                                                                                limit=limit,
                                                                                offset=offset)
    except Exception as e:
        status_message = "Error: {}".format(e)
        response.status_code = httpCodes.HTTP_400_BAD_REQUEST
        logger.error(status_message)
        raise HTTPException(
            status_code=response.status_code, 
            detail=status_message
        )
    else:
        status_message = opasCentralDBLib.API_STATUS_SUCCESS

        response.status_code = httpCodes.HTTP_200_OK
        # fill in additional return structure status info
        ret_val.sourceInfo.responseInfo.request = request.url._url

    return ret_val

#-----------------------------------------------------------------------------
#@app.get("/v1/Authors/Index/{authorNamePartial}/", response_model=models.AuthorIndex, response_model_exclude_unset=True, tags=["PEPEasy1 (Deprecated)"], summary=opasConfig.ENDPOINT_SUMMARY_AUTHOR_INDEX)
@app.get("/v2/Authors/Index/{authorNamePartial}/", response_model=models.AuthorIndex, response_model_exclude_unset=True, tags=["Authors"], summary=opasConfig.ENDPOINT_SUMMARY_AUTHOR_INDEX)
def authors_index(response: Response,
                  request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                  authorNamePartial: str=Path(..., title=opasConfig.TITLE_AUTHORNAMEORPARTIAL, description=opasConfig.DESCRIPTION_AUTHORNAMEORPARTIAL), 
                  limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                  offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                  client_id:int=Depends(get_client_id)
                        #client_session:str= Depends(get_client_session)
                  ):
    """
    ## Function
       <b>Return a list (index) of authors.  The list shows the author IDs, which are a normalized form of an authors name.</b>

    ## Return Type
       models.AuthorIndex

    ## Status
       This endpoint is working.

    ## Sample Call
       http://localhost:9100/v2/Authors/Index/Tuck/

    ## Notes

    ## Potential Errors

    """
    ret_val = None
    log_endpoint(request, client_id=client_id)
    # ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    try:
        # returns models.AuthorIndex
        author_name_to_check = authorNamePartial.lower()  # work with lower case only, since Solr is case sensitive.
        ret_val = opasPySolrLib.authors_get_author_info(author_name_to_check, limit=limit, offset=offset)
    except ConnectionRefusedError as e:
        status_message = f"The server is not running or is currently not accepting connections: {e}"
        logger.error(status_message)
        raise HTTPException(
            status_code=httpCodes.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=status_message
        )

    except Exception as e:
        status_message = f"Error: {e}"
        logger.error(status_message)
        raise HTTPException(
            status_code=httpCodes.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=status_message
        )
    else:
        status_message = opasCentralDBLib.API_STATUS_SUCCESS

        response.status_code = httpCodes.HTTP_200_OK
        # fill in additional return structure status info
        ret_val.authorIndex.responseInfo.request = request.url._url

    # for speed since this is used for author pick lists, don't log the endpoint occurrences
    #ocd.recordSessionEndpoint(apiEndpointID=opasCentralDBLib.API_AUTHORS_INDEX,
                                        #params=request.url._url,
                                        #returnStatusCode = resp.status_code = ,
                                        #statusMessage=statusMessage
                                        #)

    return ret_val  # Return author information or error

#-----------------------------------------------------------------------------
#@app.get("/v1/Authors/Publications/{authorNamePartial}/", response_model=models.AuthorPubList, response_model_exclude_unset=True, tags=["Deprecated"], summary=opasConfig.ENDPOINT_SUMMARY_AUTHOR_PUBLICATIONS)
@app.get("/v2/Authors/Publications/{authorNamePartial}/", response_model=models.AuthorPubList, response_model_exclude_unset=True, tags=["Authors"], summary=opasConfig.ENDPOINT_SUMMARY_AUTHOR_PUBLICATIONS)
def authors_publications(response: Response,
                         request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                         authorNamePartial: str=Path(..., title=opasConfig.TITLE_AUTHORNAMEORPARTIAL, description=opasConfig.DESCRIPTION_AUTHORNAMEORPARTIAL), 
                         limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                         offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                         client_id:int=Depends(get_client_id)
                               #client_session:str= Depends(get_client_session)
                         ):
    """
    ## Function
       <b>Return a list of the author's publications.</b>  
       regex style wildcards are permitted.

    ## Return Type
       models.AuthorPubList

    ## Status
       This endpoint is working.

    ## Sample Call
       http://localhost:8000/v2/Authors/Publications/Tuck/
       http://localhost:8000/v2/Authors/Publications/maslow, a.*/

    ## Notes

    ## Potential Errors

    """
    # ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)
    log_endpoint(request, client_id=client_id)

    try:
        author_name_to_check = authorNamePartial.lower()  # work with lower case only, since Solr is case sensitive.
        ret_val = opasPySolrLib.authors_get_author_publications(author_name_to_check, limit=limit, offset=offset)
    except Exception as e:
        response.status_code=httpCodes.HTTP_500_INTERNAL_SERVER_ERROR
        status_message = f"Internal Server Error: {e}"
        logger.error(status_message)
        raise HTTPException(
            status_code=response.status_code,
            detail=status_message
        )
    else:
        status_message = opasCentralDBLib.API_STATUS_SUCCESS
        ret_val.authorPubList.responseInfo.request = request.url._url
        response.status_code = httpCodes.HTTP_200_OK
        #ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_AUTHORS_PUBLICATIONS,
                                    #session_info=session_info, 
                                    #params=request.url._url,
                                    #item_of_interest=f"{authorNamePartial}", 
                                    #return_status_code = response.status_code,
                                    #status_message=status_message
                                    #)

    return ret_val

#-----------------------------------------------------------------------------
#@app.get("/v1/Documents/Abstracts/{documentID}/", response_model=models.Documents, response_model_exclude_unset=True, tags=["Deprecated"], summary=opasConfig.ENDPOINT_SUMMARY_ABSTRACT_VIEW)
@app.get("/v2/Documents/Abstracts/{documentID}/", response_model=models.Documents, response_model_exclude_unset=True, tags=["Documents"], summary=opasConfig.ENDPOINT_SUMMARY_ABSTRACT_VIEW)
def documents_abstracts(response: Response,
                        request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                        documentID: str=Path(..., title=opasConfig.TITLE_DOCUMENT_ID, description=opasConfig.DESCRIPTION_DOCIDORPARTIAL), 
                        return_format: str=Query("HTML", title=opasConfig.TITLE_RETURNFORMATS, description=opasConfig.DESCRIPTION_RETURNFORMATS),
                        similarcount: int=Query(0, title=opasConfig.TITLE_SIMILARCOUNT, description=opasConfig.DESCRIPTION_SIMILARCOUNT),
                        sort: str=Query("authors desc", title=opasConfig.TITLE_SORT, description=opasConfig.DESCRIPTION_SORT),
                        limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                        offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                        client_id:int=Depends(get_client_id), 
                        client_session:str= Depends(get_client_session)
                        ):
    """
    ## Function
       <b>Return an abstract for the requested documentID (e.g., IJP.077.0001A, or multiple abstracts
          for a partial ID (e.g., IJP.077)</b>

    ## Return Type
       models.Documents

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Documents/Abstracts/IJP.001.0203A/
         http://localhost:9100/v2/Documents/Abstracts/IJP.001.0203A/

    ## Notes
        PEP Easy 1.03Beta expects HTML abstract return (it doesn't specify a format)

    ## Potential Errors

    """
    opasDocPermissions.verify_header(request, "documents_abstracts")  # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)
    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    try:
        # authenticated = opasAPISupportLib.is_session_authenticated(request, response)
        ret_val = opasAPISupportLib.documents_get_abstracts(documentID,
                                                            ret_format=return_format,
                                                            #authenticated=authenticated,
                                                            similar_count=similarcount, 
                                                            req_url=request.url._url, 
                                                            limit=limit,
                                                            offset=offset,
                                                            sort=sort,
                                                            session_info=session_info
                                                            )
    except Exception as e:
        response.status_code=httpCodes.HTTP_400_BAD_REQUEST
        status_message = f"Error: {e}"
        logger.error(status_message)
        ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DOCUMENTS_ABSTRACTS,
                                    session_info=session_info, 
                                    params=request.url._url,
                                    item_of_interest=f"{documentID}", 
                                    return_status_code = response.status_code,
                                    status_message=status_message
                                    )
        raise HTTPException(
            status_code=response.status_code,
            detail=status_message
        )
    else:
        status_message = opasCentralDBLib.API_STATUS_SUCCESS

        #client_host = request.client.host
        # title = ret_val.documents.responseSet[0].title  # blank!
        if ret_val.documents.responseInfo.count > 0:
            response.status_code = httpCodes.HTTP_200_OK
            #  record document view if found
            ocd.record_document_view(document_id=documentID,
                                     session_info=session_info,
                                     view_type="Abstract")
        else:
            # make sure we specify an error in the session log
            #  not sure this is the best return code, but for now...
            response.status_code = httpCodes.HTTP_404_NOT_FOUND

        ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DOCUMENTS_ABSTRACTS,
                                    session_info=session_info, 
                                    params=request.url._url,
                                    item_of_interest=f"{documentID}", 
                                    return_status_code = response.status_code,
                                    status_message=status_message
                                    )
    return ret_val

@app.get("/v2/Database/Glossary/Search/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_GLOSSARY_SEARCH)
async def database_glossary_search_v2(response: Response, 
                                      request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                                      fulltext1: str=Query(None, title=opasConfig.TITLE_FULLTEXT1, description=opasConfig.DESCRIPTION_FULLTEXT1),
                                      sourcelangcode: str=Query("EN", title=opasConfig.TITLE_SOURCELANGCODE, description=opasConfig.DESCRIPTION_SOURCELANGCODE), 
                                      paratext: str=Query(None, title=opasConfig.TITLE_PARATEXT, description=opasConfig.DESCRIPTION_PARATEXT),
                                      parascope: str=Query("doc", title=opasConfig.TITLE_PARASCOPE, description=opasConfig.DESCRIPTION_PARASCOPE),
                                      synonyms: bool=Query(False, title=opasConfig.TITLE_SYNONYMS_BOOLEAN, description=opasConfig.DESCRIPTION_SYNONYMS_BOOLEAN),
                                      sort: str=Query("score desc", title=opasConfig.TITLE_SORT, description=opasConfig.DESCRIPTION_SORT),
                                      facetfields: str=Query(None, title=opasConfig.TITLE_FACETFIELDS, description=opasConfig.DESCRIPTION_FACETFIELDS), 
                                      formatrequested: str=Query("HTML", title=opasConfig.TITLE_RETURNFORMATS, description=opasConfig.DESCRIPTION_RETURNFORMATS),
                                      limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                                      highlightlimit: int=Query(opasConfig.DEFAULT_MAX_KWIC_RETURNS, title=opasConfig.TITLE_MAX_KWIC_COUNT, description=opasConfig.DESCRIPTION_MAX_KWIC_COUNT),
                                      offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET), 
                                      client_id:int=Depends(get_client_id), 
                                      client_session:str= Depends(get_client_session)
                                      ):
    """
    ## Function
       <b>Search the glossary records in the doc core (not the glossary core -- it doesn't support sub paras important for full-text search).</b>

       This is just a convenience function to search a specific book, the glossary (ZBK.069), in the doc core (pepwebdoc).

    ## Return Type
       models.Documents

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Database/Glossary/Search/

    ## Notes

       Termlist in the body is not supported by the GET function: to include a termlist, use PUT.

    ## Potential Errors
       USER NEEDS TO BE AUTHENTICATED for glossary access at the term level.  Otherwise, returns error.

       Client apps should disable the glossary links when not authenticated.
    """
    opasDocPermissions.verify_header(request, "database_glossary_search_v2") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)
    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    ret_val = await database_search_v2( response,
                                        request,
                                        fulltext1=fulltext1,
                                        smarttext=None, 
                                        paratext=paratext, #  no advanced search. Only words, phrases, prox ~ op, and booleans allowed
                                        parascope=parascope,
                                        similarcount=0, 
                                        synonyms=synonyms,
                                        sourcename=None, 
                                        sourcecode="ZBK",
                                        volume="69",
                                        sourcetype=None, 
                                        sourcelangcode=sourcelangcode,
                                        articletype=None, 
                                        issue=None, 
                                        author=None, 
                                        title=None,
                                        startyear=None,
                                        endyear=None,
                                        citecount=None,
                                        viewcount=None,
                                        viewperiod=None,
                                        formatrequested=formatrequested, 
                                        highlightlimit=highlightlimit, 
                                        facetfields=facetfields, 
                                        sort=sort,
                                        limit=limit,
                                        offset=offset,
                                        client_session=client_session,
                                        client_id=client_id
                                        )
    if ret_val != {}:
        matches = len(ret_val.documentList.responseSet)
    else:
        matches = 0

    statusMsg = f"{matches} hits"
    logger.debug(statusMsg)

    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_SEARCH,
                                session_info=session_info, 
                                params=request.url._url,
                                status_message=statusMsg
                                )

    return ret_val

#-----------------------------------------------------------------------------
# MIRROR VERSION WITH POST
#-----------------------------------------------------------------------------
@app.post("/v2/Database/Glossary/Search/", response_model=models.DocumentList, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_GLOSSARY_SEARCH)
async def database_glossary_search_v3(response: Response, 
                                      request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                                      qtermlist: models.SolrQueryTermList=None, # allows full specification
                                      fulltext1: str=Query(None, title=opasConfig.TITLE_FULLTEXT1, description=opasConfig.DESCRIPTION_FULLTEXT1),
                                      sourcelangcode: str=Query("EN", title=opasConfig.TITLE_SOURCELANGCODE, description=opasConfig.DESCRIPTION_SOURCELANGCODE), 
                                      paratext: str=Query(None, title=opasConfig.TITLE_PARATEXT, description=opasConfig.DESCRIPTION_PARATEXT),
                                      parascope: str=Query("doc", title=opasConfig.TITLE_PARASCOPE, description=opasConfig.DESCRIPTION_PARASCOPE),
                                      synonyms: bool=Query(False, title=opasConfig.TITLE_SYNONYMS_BOOLEAN, description=opasConfig.DESCRIPTION_SYNONYMS_BOOLEAN),
                                      sort: str=Query("score desc", title=opasConfig.TITLE_SORT, description=opasConfig.DESCRIPTION_SORT),
                                      facetfields: str=Query(None, title=opasConfig.TITLE_FACETFIELDS, description=opasConfig.DESCRIPTION_FACETFIELDS), 
                                      formatrequested: str=Query("HTML", title=opasConfig.TITLE_RETURNFORMATS, description=opasConfig.DESCRIPTION_RETURNFORMATS),
                                      highlightlimit: int=Query(opasConfig.DEFAULT_MAX_KWIC_RETURNS, title=opasConfig.TITLE_MAX_KWIC_COUNT, description=opasConfig.DESCRIPTION_MAX_KWIC_COUNT),
                                      limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                                      offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                                      client_id:int=Depends(get_client_id), 
                                      client_session:str= Depends(get_client_session)
                                      ):
    """
    ## Function
       <b>Search the glossary records in the doc core (not the glossary core -- it doesn't support sub paras important for full-text search).</b>

       This is just a convenience function to search a specific book, the glossary (ZBK.069), in the doc core (pepwebdoc).

    ## Return Type
       models.Documents

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Documents/Glossary/Search/

    ## Notes

    ## Potential Errors
       USER NEEDS TO BE AUTHENTICATED for glossary access at the term level.  Otherwise, returns error.

       Client apps should disable the glossary links when not authenticated.
    """
    opasDocPermissions.verify_header(request, "database_glossary_search_v3") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)
    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)
    # session_id = session_info.session_id

    ret_val = await database_search_v2b(response,
                                        request,
                                        qtermlist=qtermlist,
                                        fulltext1=fulltext1,
                                        smarttext=None, 
                                        paratext=paratext, #  no advanced search. Only words, phrases, prox ~ op, and booleans allowed
                                        parascope=parascope,
                                        similarcount=0, 
                                        synonyms=synonyms,
                                        sourcename=None, 
                                        sourcecode="ZBK",
                                        volume="69",
                                        sourcetype=None, 
                                        sourcelangcode=None,
                                        articletype=None, 
                                        issue=None, 
                                        author=None, 
                                        title=None,
                                        startyear=None,
                                        endyear=None,
                                        citecount=None,
                                        viewcount=None,
                                        viewperiod=None,
                                        highlightlimit=highlightlimit, 
                                        formatrequested=formatrequested, 
                                        facetfields=facetfields, 
                                        sort=sort,
                                        limit=limit,
                                        offset=offset, 
                                        client_session=client_session,
                                        client_id=client_id
                                        )
    if ret_val != {}:
        matches = len(ret_val.documentList.responseSet)
    else:
        matches = 0

    statusMsg = f"{matches} hits"
    logger.debug(statusMsg)

    ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DATABASE_SEARCH,
                                api_endpoint_method=opasCentralDBLib.API_ENDPOINT_METHOD_POST, 
                                session_info=session_info, 
                                params=request.url._url,
                                status_message=statusMsg
                                )

    return ret_val

#-----------------------------------------------------------------------------
@app.get("/v2/Documents/Glossary/{termIdentifier}/", response_model=models.Documents, tags=["Documents"], summary=opasConfig.ENDPOINT_SUMMARY_GLOSSARY_VIEW, response_model_exclude_unset=True)  # the current PEP API
def documents_glossary_term(response: Response,
                            request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                            termIdentifier: str=Path(..., title="Glossary Term ID or Partial ID", description=opasConfig.DESCRIPTION_GLOSSARYID),
                            termidtype: models.TermTypeIDEnum=Query(models.TermTypeIDEnum.termid, title="Type of term descriptor supplied", description=opasConfig.DESCRIPTION_TERMIDTYPE),
                            #search: str=Query(None, title="Document request from search results", description="This is a document request, including search parameters, to show hits"),
                            similarcount: int=Query(0, title=opasConfig.TITLE_SIMILARCOUNT, description=opasConfig.DESCRIPTION_SIMILARCOUNT),
                            return_format: str=Query("HTML", title=opasConfig.TITLE_RETURNFORMATS, description=opasConfig.DESCRIPTION_RETURNFORMATS),
                            client_id:int=Depends(get_client_id), 
                            client_session:str= Depends(get_client_session)
                            ): # Note this is called by the Document endpoint if it detects a term_id in the DocumentID
    """
    ## Function
       <b>Return a glossary entry for the specified {termIdentifier} if authenticated with permission.  If not, returns error.</b>

    ## Return Type
       models.Documents

    ## Status
       This endpoint is working.

    ## Sample Call
         /v2/Documents/Glossary/{termIdentifier}

    ## Notes
         In V1 (and PEP-Easy 1.0), glossary entries are fetched via the /v1/Documents endpoint rather than here.

    ## Potential Errors
       USER NEEDS TO BE AUTHENTICATED for glossary access at the term level.  Otherwise, returns error.

       Client apps should disable the glossary links when not authenticated.
    """
    ret_val = None

    opasDocPermissions.verify_header(request, "documents_glossary_term") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)
    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    try:
        # handle default passthrough, when the value becomes query.
        if not isinstance(termidtype, models.TermTypeIDEnum):
            termidtype = termidtype.default
        #  ok now look at the value
        if termidtype == "ID":
            try:
                term_parts = termIdentifier.split(".")
                if len(term_parts) == 4:
                    termIdentifier = term_parts[-2]
                elif len(term_parts) == 3:
                    termIdentifier = term_parts[-1]
                else:
                    pass
                logger.debug("Glossary View Request (termIdentifier/return_format): %s/%s", termIdentifier, return_format)
            except Exception as e:
                status_message = f"View Glossary Error: Error splitting term: {e}"
                response.status_code = httpCodes.HTTP_400_BAD_REQUEST
                logger.error(status_message)
                raise HTTPException(
                    status_code=response.status_code,
                    detail=status_message
                )

        ret_val = opasAPISupportLib.documents_get_glossary_entry(term_id=termIdentifier,
                                                                 term_id_type=termidtype,
                                                                 retFormat=return_format,
                                                                 session_info=session_info,
                                                                 req_url=request.url._url
                                                                 )

        ret_val.documents.responseInfo.request = request.url._url

    except Exception as e:
        response.status_code = httpCodes.HTTP_400_BAD_REQUEST
        status_message = f"View Glossary Error: {e}"
        logger.error(status_message)
        ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DOCUMENTS,
                                    session_info=session_info, 
                                    params=request.url._url,
                                    item_of_interest=termIdentifier, 
                                    return_status_code = response.status_code,
                                    status_message=status_message
                                    )
        raise HTTPException(
            status_code=response.status_code,
            detail=status_message
        )
    else:
        status_message = opasCentralDBLib.API_STATUS_SUCCESS

        response.status_code = httpCodes.HTTP_200_OK
        ret_val.documents.responseInfo.request = request.url._url
        ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DOCUMENTS,
                                    session_info=session_info, 
                                    params=request.url._url,
                                    item_of_interest=termIdentifier, 
                                    return_status_code = response.status_code,
                                    status_message=status_message
                                    )
    return ret_val

#-----------------------------------------------------------------------------
#@app.get("/v1/Documents/{documentID}/", response_model=models.Documents, tags=["PEPEasy1 (Deprecated)"], summary=opasConfig.ENDPOINT_SUMMARY_DOCUMENT_VIEW, response_model_exclude_unset=True)  # the current PEP API
@app.get("/v2/Documents/Document/{documentID}/", response_model=models.Documents, tags=["Documents"], summary=opasConfig.ENDPOINT_SUMMARY_DOCUMENT_VIEW, response_model_exclude_unset=True) # more consistent with the model grouping
def documents_document_fetch(response: Response,
                             request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                             documentID: str=Path(..., title=opasConfig.TITLE_DOCUMENT_ID, description=opasConfig.DESCRIPTION_DOCIDSINGLE), # return controls 
                             page:int=Query(None, title=opasConfig.TITLE_PAGEREQUEST, description=opasConfig.DESCRIPTION_PAGEREQUEST),
                             return_format: str=Query("HTML", title=opasConfig.TITLE_RETURNFORMATS, description=opasConfig.DESCRIPTION_RETURNFORMATS),
                             similarcount: int=Query(0, title=opasConfig.TITLE_SIMILARCOUNT, description=opasConfig.DESCRIPTION_SIMILARCOUNT),
                             search: str=Query(None, title=opasConfig.TITLE_SEARCHPARAM, description=opasConfig.DESCRIPTION_SEARCHPARAM),
                             pagelimit: int=Query(None,title=opasConfig.TITLE_PAGELIMIT, description=opasConfig.DESCRIPTION_PAGELIMIT),
                             pageoffset: int=Query(None, title=opasConfig.TITLE_PAGEOFFSET,description=opasConfig.DESCRIPTION_PAGEOFFSET),
                             specialoptions:int=Query(0, title=opasConfig.TITLE_SPECIALOPTIONS, description=opasConfig.DESCRIPTION_SPECIALOPTIONS), 
                             client_id:int=Depends(get_client_id), 
                             client_session:str= Depends(get_client_session)
                             ):
    """
    ## Function
        <b>Returns the Document information, document summary (absract) and full-text - but conditionally.</b>

        Returns only the summary (abstract) if non-authorized for that document via the authorization/license server (e.g., PaDS)
        
        Restricted to a single document return (partial documentID not permitted).

        To have hits marked in the full-text context, you can include a search, matching the /v2/Database/Search parameters,
           in the search parameter.  For example:
               search: fulltext1="philosophical differences"

        Parameter Additonal information
            - A Page component to the documentID, e.g., PCT.011.0171A.P0172 _is ignored_.
              This should be used by a client to jump to a page number instead.
            - limit, offset have been renamed to pagelimit, pageoffset to avoid confusion with the equivalent search parameters
            - page is an alternative to pageoffset, to use a page number from the document

    ## Return Type
       models.Documents

    ## Status
       This endpoint is working.
       
       EXPERIMENTAL:
          Use the specialoptions parameter, with an integer representing (flags) to turn on or off experimental features.
            If the feature is kept, they can be formally parameterized in a later edition.
            
            1 = Turn off glossary markup in documents
            2 = Return basic doclistinfo for any translations of the document (or original language) so
                they can be listed in a infocard or popup.  Note the original is returned in the list as well whenever there are
                translations.
                
            bitwise & these flags (full reference in opasConfig) together, e.g., 3 selects both options.  

    ## Sample Call
         http://localhost:9100/v2/Documents/Document/IJP.077.0217A/

    ## Notes
    
       Parameter "search" in the API Docs interface must include the variable name prefix "search=" to make it work
       so in the /Docs interface, the search edit field should be like:
           search=?fulltext1=adolescent
           rather than just ?fulltext1=adolescent
           
           But in the command line sent to the API it can be just:
           
                http://development.org:9100/v2/Documents/Document/ANRP.012.0129A/?return_format=xml&search=?fulltext1%3Dmultiple%20dimension&specialoptions=3

           or the longer form:
           
                http://development.org:9100/v2/Documents/Document/ANRP.012.0129A/?return_format=xml&search=?search%3D%26fulltext1%3Dmultiple%20dimension&specialoptions=3
           

    ## Potential Errors
       THE USER NEEDS TO BE AUTHENTICATED to return a document.  Otherwise an abstract/excerpt will be returned.
       Abstracts (and excerpts) are always returned in HTML

       If not authenticated:
          - The PEP developed server/API for V2 will return an abstract or summary if non-authenticated.
          - The GVPI V1 API returns an error if not authenticated

    """
    # NOTE: Calls the code for the Glossary endpoint via function view_a_glossary_entry)

    ts = time.time()
    ret_val = None
    
    session_id = client_session
    opasDocPermissions.verify_header(request, "documents_fetch") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)
    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    # check if this is a Glossary request, this is per API.v1.
    m = re.match("(ZBK\.069\..*?)?(?P<termid>(Y.0.*))", documentID)
    if m is not None:    
        # this is a glossary request, submit only the termID
        term_id = m.group("termid")
        #ret_val = view_a_glossary_entry(response, request, term_id=term_id, search=search, return_format=return_format)
        ret_val = documents_glossary_term(response, request, termIdentifier=term_id, return_format=return_format)
    else:
        # notes:
        #  if a page extension to the docid is supplied, it is ignored. The client should use that instead to jump to that page.
        # m = re.match("(?P<docid>[A-Z]{2,12}\.[0-9]{3,3}[A-F]?\.(?P<pagestart>[0-9]{4,4})[A-Z]?)(\.P(?P<pagenbr>[0-9]{4,4}))?", documentID)
        #if m is not None:
            #documentID = m.group("docid")
            #page_number = m.group("pagenbr")
            #if page_number is not None:
                #try:
                    #page_start_int = int(m.group("pagestart"))
                    #page_number_int = int(page_number)
                    #pageoffset = page_number_int - page_start_int
                #except Exception as e:
                    #logger.error(f"Page offset calc issue.  {e}")
                    #pageoffset = 0

        # TODO: do we really need to do this extra query?  Why not just let get_document do the work?
        # doc_info = opasAPISupportLib.document_get_info(documentID,
                                                        #fields="art_id, art_sourcetype, art_year, file_classification, art_sourcecode")
        # file_classification = doc_info.get("file_classification", opasConfig.DOCUMENT_ACCESS_UNDEFINED)
        try:
            # documents_get_document handles the view authorization and returns abstract if not authenticated.
            if search is not None:
                argdict = dict(parse.parse_qsl(parse.urlsplit(search).query))
                try:
                    # if there's an abstract parameter, rename it to abstract_requested (used because that's clearer in code params, so that's what the underlying functions use)
                    argdict["abstract_requested"] = argdict.pop("abstract")
                    print ("Fulltext1:" + f'{argdict.get("fulltext1", "")}')
                except KeyError:
                    pass # no abstract param. skip.
                
                if documentID is not None:
                    # make sure this is part of the last search set.
                    j = argdict.get("journal")
                    if j is not None:
                        if j not in documentID:
                            argdict["journal"] = None
            else:
                argdict = {}

            solr_query_params = opasQueryHelper.parse_search_query_parameters(**argdict)
            logger.debug("Document View Request: %s/%s/%s", solr_query_params, documentID, return_format)

            ret_val = opasAPISupportLib.documents_get_document( documentID, 
                                                                solr_query_params,
                                                                ret_format=return_format,
                                                                similar_count=similarcount, 
                                                                page_offset=pageoffset, # starting page
                                                                page_limit=pagelimit, # number of pages
                                                                page=page, # specific page number request (rather than offset),
                                                                req_url=request.url._url, 
                                                                session_info=session_info,
                                                                option_flags=specialoptions
                                                                )

            try:
                supplemental = opasPySolrLib.metadata_get_next_and_prev_articles(art_id=documentID)
                if supplemental[0] != {}:
                    ret_val.documents.responseSet[0].sourcePrevious = supplemental[0]["art_id"]
                if supplemental[2] != {}:
                    ret_val.documents.responseSet[0].sourceNext = supplemental[2]["art_id"]
            except Exception as e:
                logger.debug(f"No next/prev data to return ({e})")
        
        except Exception as e:
            response.status_code=httpCodes.HTTP_400_BAD_REQUEST
            status_message = f"{client_id}:{session_id}: Document Fetch Error: {e}"
            logger.error(status_message)
            ret_val = None
            raise HTTPException(
                status_code=response.status_code,
                detail=status_message
            )
        else:
            if ret_val is not None and ret_val != {}:
                response.status_code = httpCodes.HTTP_200_OK
                status_message = opasCentralDBLib.API_STATUS_SUCCESS
                try:
                    access = not ret_val.documents.responseSet[0].accessLimited
                    doc_len = len(ret_val.documents.responseSet[0].document)
                except Exception as e:
                    access = False
                    doc_len = 0
                    status_message = f"{client_id}:{session_id}: Document fetch Error {e}"
                    logger.info(status_message)
                else:
                    if access == False:
                        status_message = f"{client_id}:{session_id}: Document (Abstract only) fetch (access: {access}; doc length: {doc_len}"
                    else:
                        status_message = f"{client_id}:{session_id}: Document fetch (access: {access}; doc length: {doc_len}"

                    logger.info(status_message)

            else:
                # make sure we specify an error in the session log
                # not sure this is the best return code, but for now...
                status_message = "Not Found"
                response.status_code = httpCodes.HTTP_404_NOT_FOUND
                # record session endpoint in any case   

            ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DOCUMENTS,
                                        session_info=session_info, 
                                        params=request.url._url,
                                        item_of_interest=documentID, 
                                        return_status_code = response.status_code,
                                        status_message=status_message
                                        )

            if ret_val is None or ret_val == {}:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=status_message
                )           
            else:
                ret_val.documents.responseInfo.request = request.url._url
                if access == False:
                    #  abstract returned...we don't count those currently.
                    logger.info(f"Document request for non-logged-in user (session: {session_info.session_id}). Abstract returned instead for {documentID}.")
                else:
                    if ret_val.documents.responseInfo.count > 0:
                        #  record document view if found
                        ocd.record_document_view(document_id=documentID,
                                                 session_info=session_info,
                                                 view_type="Document")
                    else:
                        logger.debug(f"No document returned for request: {documentID} during session {session_info.session_id}")

    log_endpoint_time(request, ts=ts)
    return ret_val

#-----------------------------------------------------------------------------
@app.get("/v2/Documents/Concordance", response_model=models.Documents, tags=["Documents"], summary=opasConfig.ENDPOINT_SUMMARY_CONCORDANCE, response_model_exclude_unset=True)  # the current PEP API
def documents_concordance(response: Response,
                          request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                          paralangid: str=Query(None, title=opasConfig.TITLE_DOCUMENT_CONCORDANCE_ID, description=opasConfig.DESCRIPTION_DOCUMENT_CONCORDANCE_ID), # return controls 
                          paralangrx: str=Query(None, title=opasConfig.TITLE_DOCUMENT_CONCORDANCE_RX, description=opasConfig.DESCRIPTION_DOCUMENT_CONCORDANCE_RX), # return controls 
                          return_format: str=Query("HTML", title=opasConfig.TITLE_RETURNFORMATS, description=opasConfig.DESCRIPTION_RETURNFORMATS),
                          search: str=Query(None, title=opasConfig.TITLE_SEARCHPARAM, description=opasConfig.DESCRIPTION_SEARCHPARAM),
                          client_id:int=Depends(get_client_id), 
                          client_session:str= Depends(get_client_session)
                          ):
    """
    ## Function
        <b>Returns the translation paragraph identified by the unique para ID(s) .</b>

    ## Return Type
       models.Documents

    ## Status
       This endpoint is working.

    ## Sample Call
         http://localhost:9100/v2/Documents/Document/IJP.077.0217A/

    ## Notes

    ## Potential Errors
       THE USER NEEDS TO BE AUTHENTICATED to return a para.

    """
    # NOTE: Calls the code for the Glossary endpoint via function view_a_glossary_entry)

    ret_val = None
    item_of_interest = f"{paralangid}/{paralangrx}"

    opasDocPermissions.verify_header(request, "documents_concordance") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)
    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    try:
        ##  this may not be useful...if so, remove and remove parameter.
        #if search is not None:
            #argdict = dict(parse.parse_qsl(parse.urlsplit(search).query))
        #else:
            #argdict = {}
        #solr_query_params = opasQueryHelper.parse_search_query_parameters(**argdict)
        #logger.debug("Concordance View Request: %s/%s/%s", solr_query_params, f"{paralangid} / {paralangrx}", return_format)

        ret_val = opasAPISupportLib.documents_get_concordance_paras( paralangid,
                                                                     paralangrx, 
                                                                     #solr_query_params,
                                                                     ret_format=return_format,
                                                                     req_url=request.url._url, 
                                                                     session_info=session_info
                                                                     )
    except Exception as e:
        response.status_code=httpCodes.HTTP_400_BAD_REQUEST
        status_message = f"Para Fetch Error: {e}"
        logger.error(status_message)
        ret_val = None
        ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DOCUMENTS,
                                    session_info=session_info, 
                                    params=request.url._url,
                                    item_of_interest=item_of_interest, 
                                    return_status_code = response.status_code,
                                    status_message=status_message
                                    )
        raise HTTPException(
            status_code=response.status_code,
            detail=status_message
        )
    else:
        if ret_val != {}:
            response.status_code = httpCodes.HTTP_200_OK
            status_message = opasCentralDBLib.API_STATUS_SUCCESS
        else:
            # make sure we specify an error in the session log
            # not sure this is the best return code, but for now...
            status_message = "Not Found"
            response.status_code = httpCodes.HTTP_404_NOT_FOUND

        ocd.record_session_endpoint(api_endpoint_id=opasCentralDBLib.API_DOCUMENTS,
                                    session_info=session_info, 
                                    params=request.url._url,
                                    item_of_interest=item_of_interest, 
                                    return_status_code = response.status_code,
                                    status_message=status_message
                                    )

        if ret_val == {}:
            raise HTTPException(
                status_code=response.status_code,
                detail=status_message
            )           

    return ret_val

#-----------------------------------------------------------------------------
#@app.get("/v1/Documents/Downloads/Images/{imageID}/", response_model_exclude_unset=True, tags=["PEPEasy1 (Deprecated)"], summary=opasConfig.ENDPOINT_SUMMARY_IMAGE_DOWNLOAD)
@app.get("/v2/Documents/Image/{imageID}/", response_model_exclude_unset=True, tags=["Documents"], summary=opasConfig.ENDPOINT_SUMMARY_IMAGE_DOWNLOAD)
async def documents_image_fetch(response: Response,
                                request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                                imageID: str=Path(..., title=opasConfig.TITLE_IMAGEID, description=opasConfig.DESCRIPTION_IMAGEID),
                                download: int=Query(0, title="Return or download", description="0 to return the image to the browser, 1 to download"),
                                client_id:int=Depends(get_client_id), 
                                #client_session:str= Depends(get_client_session)
                                ):
    """
    ## Function
       <b>Returns a binary image per the GVPi server</b>
       if download == 1 then the file is returned as a downloadable file to the client/browser.
       Otherwise, it's returned as binary data, and displays in the browser.  This is in fact
          how it works to display images in articles.

    ## Return Type
       Binary data

    ## Status
       This endpoint is working.


    ## Sample Call
         http://localhost:9100/v1/Documents/Image/AIM.036.0275A.FIG001/
         http://development.org:9100/v/Documents/Image/AIM.036.0275A.FIG001

    ## Notes

    ## Potential Errors
       USER NEEDS TO BE AUTHENTICATED to request a download.  Otherwise, returns error.
    """
    ret_val = None
    if imageID is not None:
        imageID = imageID.replace("+", " ")

    log_endpoint(request, client_id=client_id)

    endpoint = opasCentralDBLib.API_DOCUMENTS_IMAGE
    if download != 0:
        client_session = get_client_session(response, request, 
                                            client_id=client_id) 
        # this is when we need a session id
        opasDocPermissions.verify_header(request, "DocumentImage") # for debugging client call
        ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

        # allow viewing, but not downloading if not logged in
        if not session_info.authenticated:
            response.status_code = httpCodes.HTTP_400_BAD_REQUEST 
            status_message = "Must be logged in and authorized to download an image."
            logger.warning(status_message)
            raise HTTPException(
                status_code=response.status_code,
                detail=status_message
            )    

    fs = opasFileSupport.FlexFileSystem(key=localsecrets.S3_KEY, secret=localsecrets.S3_SECRET, root=localsecrets.IMAGE_SOURCE_PATH)
    filename = fs.get_image_filename(filespec=imageID) # IMAGE_SOURCE_PATH set as root above, all that we need
    media_type='image/jpeg'
    if download == 0:
        if filename is None:
            response.status_code = httpCodes.HTTP_400_BAD_REQUEST 
            status_message = f"Error: {imageID} not found or no filename specified"
            logger.warning(status_message)
            raise HTTPException(status_code=response.status_code,
                                detail=status_message)
        else:
            file_content = fs.get_image_binary(filename)
            try:
                ret_val = response = Response(file_content, media_type=media_type)

            except Exception as e:
                response.status_code = httpCodes.HTTP_400_BAD_REQUEST 
                status_message = f" The requested document {filename} could not be returned {e}"
                logger.warning(status_message)
                raise HTTPException(status_code=response.status_code,
                                    detail=status_message)

            else:
                status_message = opasCentralDBLib.API_STATUS_SUCCESS
                logger.debug(status_message)

    else: # download == 1
        try:
            response.status_code = httpCodes.HTTP_200_OK
            filename = fs.get_image_filename(filename)
            if fs.key is not None:
                fileurl = fs.fs.url(filename)
                fname = wget.download(fileurl)
                ret_val = FileResponse(path=fname,
                                       status_code=response.status_code,
                                       filename=os.path.split(fname)[1], 
                                       media_type=media_type)
            else:
                fileurl = filename
                ret_val = FileResponse(path=fileurl,
                                       status_code=response.status_code,
                                       filename=os.path.split(filename)[1], 
                                       media_type=media_type)


        except Exception as e:
            response.status_code = httpCodes.HTTP_400_BAD_REQUEST 
            status_message = f" The requested document {filename} could not be returned {e}"
            raise HTTPException(status_code=response.status_code,
                                detail=status_message)

        else:
            status_message = opasCentralDBLib.API_STATUS_SUCCESS

            logger.debug(status_message)
            ocd.record_document_view(document_id=imageID,
                                     session_info=session_info,
                                     view_type="file_format")
            ocd.record_session_endpoint(api_endpoint_id=endpoint,
                                        session_info=session_info, 
                                        params=request.url._url,
                                        item_of_interest=f"{imageID}", 
                                        return_status_code = response.status_code,
                                        status_message=status_message
                                        )

    return ret_val

#-----------------------------------------------------------------------------
#@app.get("/v1/Documents/Downloads/{retFormat}/{documentID}/", response_model_exclude_unset=True, tags=["PEPEasy1 (Deprecated)"], summary=opasConfig.ENDPOINT_SUMMARY_DOCUMENT_DOWNLOAD)
@app.get("/v2/Documents/Downloads/{retFormat}/{documentID}/", response_model_exclude_unset=True, tags=["Documents"], summary=opasConfig.ENDPOINT_SUMMARY_DOCUMENT_DOWNLOAD)
def documents_downloads(response: Response,
                        request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),  
                        documentID: str=Path(..., title=opasConfig.TITLE_DOCUMENT_ID, description=opasConfig.DESCRIPTION_DOCIDORPARTIAL), 
                        retFormat=Path(..., title=opasConfig.TITLE_RETURNFORMATS, description=opasConfig.DESCRIPTION_DOCDOWNLOADFORMAT),
                        client_id:int=Depends(get_client_id), 
                        client_session:str= Depends(get_client_session)
                        ):
    """
    ## Function
       <b>Initiates download of the document in EPUB or PDF format (if authenticated)</b>

    ## Return Type
       initiates a download of the requested document type

    ## Status
       This endpoint is working.
       There may be more work needed on the conversions:
          ePub conversion (links go nowhere in the tests I did' need to compare to GVPi version)
          PDF conversion (formatting is not great)

    ## Sample Call
         http://localhost:9100/v2/Documents/Downloads/EPUB/IJP.077.0217A/
         http://localhost:9100/v2/Documents/Downloads/PDF/IJP.077.0217A/
         http://localhost:9100/v2/Documents/Downloads/PDFORIG/IJP.077.0217A/

    ## Notes

    ## Potential Errors
       USER NEEDS TO BE AUTHENTICATED to request a download.  Otherwise, returns error.
    """
    ts = time.time()
    opasDocPermissions.verify_header(request, "documents_downloads") # for debugging client call
    log_endpoint(request, client_id=client_id, session_id=client_session)
    ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    if retFormat.upper() == "EPUB":
        file_format = 'EPUB'
        media_type='application/epub+zip'
        endpoint = opasCentralDBLib.API_DOCUMENTS_EPUB
    elif retFormat.upper() == "PDF":
        file_format = 'PDF'
        media_type='application/pdf'
        endpoint = opasCentralDBLib.API_DOCUMENTS_PDF
    elif retFormat.upper() == "PDFORIG":  # not yet implemented.
        file_format = 'PDFORIG'
        media_type='application/pdf'
        endpoint = opasCentralDBLib.API_DOCUMENTS_PDFORIG
    else:
        file_format = 'HTML'
        media_type='application/xhtml+xml'
        endpoint = opasCentralDBLib.API_DOCUMENTS_HTML

    #prep_document_download will check permissions for this user, and return abstract based file
    #if there's no permission
    flex_fs = opasFileSupport.FlexFileSystem(key=localsecrets.S3_KEY,
                                             secret=localsecrets.S3_SECRET,
                                             root=localsecrets.PDF_ORIGINALS_PATH) # important to use this path, not the XML one!

    filename, status = opasPySolrLib.prep_document_download( documentID,
                                                             ret_format=file_format,
                                                             base_filename="opasDoc",
                                                             session_info=session_info, 
                                                             flex_fs=flex_fs,
                                                            )    

    error_status_message = f" The requested document {documentID} could not be returned."

    if filename is None:
        response.status_code = status.httpcode
        status_message = status.error_description + error_status_message
        logger.error(status_message)
        raise HTTPException(status_code=response.status_code,
                            detail=status_message)
    else:
        if file_format == 'PDFORIG':
            try:
                if flex_fs.key is not None:
                    fileurl = flex_fs.fs.url(filename)
                    fname = wget.download(fileurl)
                    response.status_code = httpCodes.HTTP_200_OK
                    ret_val = FileResponse(path=fname,
                                           status_code=response.status_code,
                                           filename=os.path.split(fname)[1], 
                                           media_type=media_type)
                else:
                    fileurl = filename
                    response.status_code = httpCodes.HTTP_200_OK
                    ret_val = FileResponse(path=fileurl,
                                           status_code=response.status_code,
                                           filename=os.path.split(filename)[1], 
                                           media_type=media_type)
            except Exception as e:
                response.status_code = httpCodes.HTTP_400_BAD_REQUEST 
                raise HTTPException(status_code=response.status_code,
                                    detail=error_status_message)
            else:
                status_message = opasCentralDBLib.API_STATUS_SUCCESS

                logger.info(status_message)
                ocd.record_document_view(document_id=documentID,
                                         session_info=session_info,
                                         view_type=file_format)

                ocd.record_session_endpoint(api_endpoint_id=endpoint,
                                            session_info=session_info, 
                                            params=request.url._url,
                                            item_of_interest=f"{documentID}", 
                                            return_status_code = response.status_code,
                                            status_message=status_message
                                            )

        else:
            try:
                response.status_code = httpCodes.HTTP_200_OK
                ret_val = FileResponse(path=filename,
                                       status_code=response.status_code,
                                       filename=os.path.split(filename)[1], 
                                       media_type=media_type)

            except Exception as e:
                response.status_code = httpCodes.HTTP_400_BAD_REQUEST 
                status_message = f" The requested document {filename} could not be returned {e}"
                raise HTTPException(status_code=response.status_code,
                                    detail=status_message)

            else:
                status_message = opasCentralDBLib.API_STATUS_SUCCESS

                logger.info(status_message)
                ocd.record_document_view(document_id=documentID,
                                         session_info=session_info,
                                         view_type=file_format)
                ocd.record_session_endpoint(api_endpoint_id=endpoint,
                                            session_info=session_info, 
                                            params=request.url._url,
                                            item_of_interest=f"{documentID}", 
                                            return_status_code = response.status_code,
                                            status_message=status_message
                                            )

    log_endpoint_time(request, ts=ts)
    return ret_val

@app.get("/v2/Database/WordWheel/", response_model=models.TermIndex, response_model_exclude_unset=True, tags=["Database"], summary=opasConfig.ENDPOINT_SUMMARY_WORD_WHEEL)
def database_word_wheel(response: Response,
                        request: Request=Query(None, title=opasConfig.TITLE_REQUEST, description=opasConfig.DESCRIPTION_REQUEST),
                        word: str=Query(None, title=opasConfig.TITLE_WORD, description=opasConfig.DESCRIPTION_WORD),
                        field: str=Query("text", title=opasConfig.TITLE_WORDFIELD, description=opasConfig.DESCRIPTION_WORDFIELD),
                        core: str=Query("docs", title=opasConfig.TITLE_CORE, description=opasConfig.DESCRIPTION_CORE),
                        limit: int=Query(opasConfig.DEFAULT_LIMIT_FOR_SOLR_RETURNS, title=opasConfig.TITLE_LIMIT, description=opasConfig.DESCRIPTION_LIMIT),
                        #offset: int=Query(0, title=opasConfig.TITLE_OFFSET, description=opasConfig.DESCRIPTION_OFFSET),
                        startat:str=Query(None, title="Start at this term/prefix (inconsistent at best)."), 
                        client_id:int=Depends(get_client_id), 
                         #client_session:str= Depends(get_client_session)
                        ):
    """
    ## Function
       <b>Return a list (termIndex) of words for the field matching the prefix.</b>

       Implement a word wheel function in the calling app.

       The field must be a derivative of class solr.TextField. In the PEP implementation,  that includes:
            text, text_general, text_simple, text_general_syn
            string_ci (case insensitive string, TextField based)

       The field does not need to be one that's actually "stored".

       Examples of applicable fields from solr core docs for PEP:
             text - full-text document search
             para or art_para - full-text, all paragraphs (para is level 2, art_para is level 1)
             art_authors - string_ci, returns matching full names (authors is string, so it cannot be used)
             art_authors_xml - text, returns matching components of names
             quotes_spkr
             headings_xml - text
             capt
             authors - string_ci, full names
             terms_xml
             glossary_terms, glossary_group_terms - string_ci
             art_kwds - text
             art_kwds_str - string_ci 

       The default field text is in the docs core; currently docs and authors are the only cores supported.

       This endpoint return word counts for the words returned; it can also be used to check the number of instances of a search
       term, to determine if it's going to be effective by itself in limiting the results.


    ## Return Type
       models.termIndex

    ## Status
       This endpoint is working.

    ## Sample Call
       http://localhost:9100/v2/WordWheel?phleb

    ## Notes

    ## Potential Errors

    """
    ret_val = None
    # print (f"Called WordWheel: {word}")
    # ocd, session_info = opasAPISupportLib.get_session_info(request, response, session_id=client_session, client_id=client_id)

    if core in ["docs", "authors"] and word is not None:
        try:
            # returns models.TermIndex
            term_to_check = word.lower()  # work with lower case only, since Solr is case sensitive.
            ret_val = opasPySolrLib.get_term_index(term_to_check,
                                                   term_field=field,
                                                   core=core,
                                                   req_url=request.url, 
                                                   limit=limit,
                                                   start_at=startat)
        except ConnectionRefusedError as e:
            status_message = f"The server is not running or is currently not accepting connections: {e}"
            logger.error(status_message)
            raise HTTPException(
                status_code=httpCodes.HTTP_503_SERVICE_UNAVAILABLE,
                detail=status_message
            )
        except Exception as e:
            status_message = f"Internal Server Error: {e}"
            logger.error(status_message)
            raise HTTPException(
                status_code=httpCodes.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=status_message
            )
        else:
            status_message = opasCentralDBLib.API_STATUS_SUCCESS
            response.status_code = httpCodes.HTTP_200_OK
    else:
        if word is not None:
            status_message = f"Unsupported Core: {core}"
        else:
            status_message = f"No word supplied."
        logger.error(status_message)
        raise HTTPException(
            status_code=httpCodes.HTTP_400_BAD_REQUEST,
            detail=status_message
        )

    # for maximum speed since this is used for word_wheels, don't log the endpoint occurrences
    return ret_val  # Return author information or error


if __name__ == "__main__":
    from localsecrets import CONFIG
    print(f"Server Running ({localsecrets.BASEURL}:{localsecrets.API_PORT_MAIN})")
    print (f"Running in Python {sys.version_info[0]}.{sys.version_info[1]}")
    print (f"Configuration used: {CONFIG}")
    uvicorn.run(app, host="development.org", port=localsecrets.API_PORT_MAIN, debug=False, log_level="warning")
    # uvicorn.run(app, host=localsecrets.BASEURL, port=9100, debug=True)
    print ("Now we're exiting...")