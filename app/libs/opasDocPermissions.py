#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import datetime
import time
import opasConfig
import models
import logging
import localsecrets
import urllib.parse
import json
import sys
import inspect

# from opasAPISupportLib import save_opas_session_cookie
sys.path.append("..") # Adds higher directory to python modules path.
from config.opasConfig import OPASSESSIONID

logger = logging.getLogger(__name__)
# for this module
# logger.setLevel(logging.DEBUG)

if 0:
    # create console handler and set level to debug
    ch = logging.StreamHandler()
    # create formatter
    formatter = logging.Formatter(opasConfig.FORMAT)
    # add formatter to ch
    ch.setFormatter(formatter)
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)

from starlette.responses import JSONResponse, Response
from starlette.requests import Request
import starlette.status as httpCodes

# import localsecrets
from localsecrets import PADS_TEST_ID, PADS_TEST_PW, PADS_BASED_CLIENT_IDS
base = "https://padstest.zedra.net/PEPSecure/api"
# base = "http://development.org:9300"
import opasCentralDBLib

def verify_header(request, caller_name):
    # Double Check for missing header test--ONLY checks headers, not other avenues used by find
    client_session_from_header = request.headers.get(opasConfig.CLIENTSESSIONID, None)
    client_id_from_header = request.headers.get(opasConfig.CLIENTID, None)
    if client_session_from_header == None:
        logger.error(f"***{caller_name}*** - No client-session supplied. Client-id (from header): {client_id_from_header}.")

def find_client_session_id(request: Request,
                           response: Response,
                           client_session: str=None
                           ):
    """
    ALWAYS returns a session ID or None
    
    Dependency for client_session id:
           gets it from header;
           if not there, gets it from query param;
           if not there, gets it from a cookie
           Otherwise, gets a new one from the auth server
    """
    ret_val = None

    if client_session is None or client_session == 'None':
        client_session = request.headers.get(opasConfig.CLIENTSESSIONID, None)
    
    if client_session is not None:
        ret_val = client_session
        #msg = f"client-session from header: {ret_val} "
        #logger.debug(msg)
    else:
        #Won't work unless they expose cookie to client, so don't waste time 
        #pepweb_session_cookie = request.cookies.get("pepweb_session", None)
        opas_session_cookie = request.cookies.get(opasConfig.OPASSESSIONID, None)
        client_session_qparam = request.query_params.get(opasConfig.CLIENTSESSIONID, None)
        client_session_cookie = request.cookies.get(opasConfig.CLIENTSESSIONID, None)
        if client_session_qparam is not None:
            ret_val = client_session_qparam
            msg = f"client-session from param: {ret_val} "
            logger.debug(msg)
        elif client_session_cookie is not None:
            ret_val = client_session_cookie
            msg = f"client-session from client-session cookie: {ret_val} "
            logger.debug(msg)
        elif opas_session_cookie is not None and opas_session_cookie != 'None':
            msg = f"client-session from stored OPASSESSION cookie {opas_session_cookie}"
            logger.debug(msg)
            ret_val = opas_session_cookie
        else:
            msg = f"No client-session ID found. Returning None"
            logger.debug(msg)
            ret_val = None

        if ret_val is not None and opas_session_cookie is not None and opas_session_cookie != ret_val:
            #  overwrite any saved cookie, if there is one
            logger.debug("Saved OpasSessionID Cookie")
            response.set_cookie(
                OPASSESSIONID,
                value=f"{client_session}",
                domain=localsecrets.COOKIE_DOMAIN
            )

    return ret_val

def find_client_id(request: Request,
                   response: Response,
                  ):
    """
    ALWAYS returns a client ID.
    
    Dependency for client_id:
           gets it from header;
           if not there, gets it from query param;
           if not there, defaults to 0 (server is client)
    """
    #client_id = int(request.headers.get("client-id", '0'))
    ret_val = 0
    client_id = request.headers.get(opasConfig.CLIENTID, None)
    client_id_qparam = request.query_params.get(opasConfig.CLIENTID, None)
    client_id_cookie = request.cookies.get(opasConfig.CLIENTID, None)
    pepweb_session_cookie = request.cookies.get("pepweb_session", None)
    if client_id is not None:
        ret_val = client_id
        msg = f"client-id from header: {ret_val} "
        logger.debug(msg)
    elif client_id_qparam is not None:
        ret_val = client_id_qparam
        msg = f"client-id from param: {ret_val} "
        logger.debug(msg)
    elif client_id_cookie is not None:
        ret_val = client_id_cookie
        msg = f"client-id from cookie: {ret_val} "
        logger.debug(msg)
    elif pepweb_session_cookie is not None:
        ret_val = 2 #  pep-web client
        msg = f"client-id inferred from pepweb-session cookie: {ret_val} "
        logger.debug(msg)
    else:
        ret_val = opasConfig.NO_CLIENT_ID # no client id

    return ret_val

def fix_pydantic_invalid_nones(response_data):
    try:
        if response_data["ReasonStr"] is None:
            response_data["ReasonStr"] = ""
    except Exception as e:
        logger.error(f"Exception: {e}")

    return response_data

def get_authserver_session_info(session_id, client_id, pads_session_info=None):
    """
    Return a filled-in SessionInfo object from several PaDS calls
    
    >>> session_info = get_authserver_session_info(None, "4")
    >>> session_info.username == "NotLoggedIn"
    True
    
    >>> pads_session_info = pads_login()
    >>> session_id = pads_session_info.SessionId
    >>> session_info = get_authserver_session_info(session_id, "4", pads_session_info=pads_session_info)
    >>> session_info.authorized_peparchive == True
    True

    >>> session_info = get_authserver_session_info("7F481226-9AF1-47BC-8E26-F07DB8C3E78D", "4")
    >>> print (session_info)
    session_id='7F481226-9AF1-47BC-8E26-F07DB8C3E78D' user_id=0 username='NotLoggedIn' ...
    >>> session_info.username == "NotLoggedIn"
    True
    
    
    """
    ts = time.time()
    
    logger.info(f"get_authserver_session_info called by {inspect.stack()[1].function}")
    if pads_session_info is None or session_id is None:
        # not supplied, so fetch
        pads_session_info = get_pads_session_info(session_id=session_id, client_id=client_id, retry=False)
        session_info = models.SessionInfo(session_id=pads_session_info.SessionId, api_client_id=client_id)
        session_id = session_info.session_id
    else:
        session_info = models.SessionInfo(session_id=session_id, api_client_id=client_id)
        
    if pads_session_info is not None:
        start_time = pads_session_info.session_start_time if pads_session_info.session_start_time is not None else datetime.datetime.now()
        session_info.has_subscription = pads_session_info.HasSubscription
        session_info.is_valid_login = pads_session_info.IsValidLogon
        session_info.is_valid_username = pads_session_info.IsValidUserName
        session_info.authenticated = pads_session_info.IsValidLogon
        session_info.confirmed_unauthenticated = False
        session_info.session_start = start_time
        session_info.session_expires_time = start_time + datetime.timedelta(seconds=pads_session_info.SessionExpires)
        session_info.pads_session_info = pads_session_info
        
    # either continue an existing session, or start a new one
    pads_user_info, status_code = get_authserver_session_userinfo(session_id, client_id)
    session_info.pads_user_info = pads_user_info
    if status_code == 401:
        if session_info.pads_session_info.pads_status_response > 500:
            msg = "PaDS error or PaDS unavailable - user cannot be logged in and no session_id assigned"
            logger.error(msg)
        # session is not logged in
        session_info.confirmed_unauthenticated = True
        # these are defaults so commented out
        # session_info.authenticated = False
        # session_info.user_id = 0
        # session_info.username = opasConfig.USER_NOT_LOGGED_IN_NAME
        # session_info.user_type = "Unknown"
        # session_info.admin = False
        # session_info.authorized_peparchive = False
        # session_info.authorized_pepcurrent = False
    else:
        start_time = pads_session_info.session_start_time if pads_session_info.session_start_time is not None else datetime.datetime.now()
        if pads_user_info is not None:
            session_info.user_id = userID=pads_user_info.UserId
            session_info.username = pads_user_info.UserName
            session_info.user_type = pads_user_info.UserType
            session_info.admin = pads_user_info.UserType=="Admin"
            session_info.authorized_peparchive = pads_user_info.HasArchiveAccess
            session_info.authorized_pepcurrent = pads_user_info.HasCurrentAccess
            logger.info("PaDS returned user info.  Saving to DB")
            unused_val = save_session_info_to_db(session_info)
            
    # print (f"SessInfo: {session_info}")
    logger.info(f"***authent: {session_info.authenticated} - get_full_session_info total time: {time.time() - ts}***")
    return session_info

def get_authserver_session_userinfo(session_id, client_id):
    """
    Send PaDS the session ID and see if that's associated with a user yet.
    """
    ret_val = None
    status_code = 401
    msg = f"get_user_info for session {session_id} from client {client_id}"
    logger.debug(msg)
    if session_id is not None:
        full_URL = base + f"/v1/Users" + f"?SessionID={session_id}"
        try:
            response = requests.get(full_URL, headers={"Content-Type":"application/json"})
        except Exception as e:
            msg = f"No user info from authorization server {e}. Non-logged in user for sessionId: {session_id} client-id {client_id}."
            logger.error(msg)
        else:
            status_code = response.status_code
            padsinfo = response.json()
            if response.ok:
                ret_val = models.PadsUserInfo(**padsinfo)
            else:
                logger.info(f"Non-logged in user for client-id {client_id} sessionId: {session_id}. Info from PaDS: {padsinfo}")
            
    return ret_val, status_code # padsinfo, status_code
    
def save_session_info_to_db(session_info):
    # make sure the session is recorded.
    session_id = session_info.session_id
    ocd = opasCentralDBLib.opasCentralDB()
    db_session_info = ocd.get_session_from_db(session_id)
    if db_session_info is None:
        ret_val, saved_session_info = ocd.save_session(session_id, session_info)
        logger.info(f"Saving session info {session_id}")
    else:
        logger.info(f"Session {session_id} already found in db. Updating...")
        if session_info.username != db_session_info.username and db_session_info.username != opasConfig.USER_NOT_LOGGED_IN_NAME:
            msg = f"MISMATCH! Two Usernames with same session_id. OLD(DB): {db_session_info}; NEW(SESSION): {session_info}"
            print (msg)
            logger.error(msg)
        
        logger.info(f"Updating session info {session_id}")
        ret_val = ocd.update_session(session_id,
                                     userID=session_info.user_id,
                                     username=session_info.username, 
                                     authenticated=1 if session_info.authenticated == True else 0,
                                     authorized_peparchive=1 if session_info.authorized_peparchive == True else 0,
                                     authorized_pepcurrent=1 if session_info.authorized_pepcurrent == True else 0,
                                     session_end=session_info.session_expires_time,
                                     api_client_id=session_info.api_client_id
                                     )
    
    return ret_val

def authserver_login(username=PADS_TEST_ID, password=PADS_TEST_PW, session_id=None, client_id=opasConfig.NO_CLIENT_ID, retry=True):
    """
    Login directly via the auth server (e.g., in this case PaDS)
    
    If session_id is included, the idea is that the logged in entity will keep that constant.
      -- #TODO but that's not implemented in this server itself, if logged in through there, yet!
      
    """
    msg = ""
    logger.info(f"Logging in user {username} with session_id {session_id}")
    if session_id is not None:
        full_URL = base + f"/v1/Authenticate/" # + f"?SessionId={session_id}"
    else:
        full_URL = base + f"/v1/Authenticate/"

    try:
        pads_response = requests.post(full_URL, headers={"Content-Type":"application/json"}, json={"UserName":f"{username}", "Password":f"{password}"})
    except Exception as e:
        msg = f"PaDS Authorization server not available. {e}"
        logger.error(msg)
        print (f"****WATCH_THIS****: {msg}")
        # set up response with default model
        pads_session_info = models.PadsSessionInfo()
        if session_id is not None:
            pads_session_info.SessionId = session_id 
        #session_info = models.SessionInfo()
    else:
        status_code = pads_response.status_code # save it for a bit (we replace pads_session_info below)
        if pads_response.ok:
            pads_response = pads_response.json()
            pads_response = fix_pydantic_invalid_nones(pads_response)
            if isinstance(pads_response, str):
                pads_session_info = models.PadsSessionInfo()
                logger.error(f"Pads returned error string: {pads_response}")
            else:
                try:
                    pads_session_info = models.PadsSessionInfo(**pads_response)
                except Exception as e:
                    logger.error(f"Pads return assignment error: {e}")
                    pads_session_info = models.PadsSessionInfo()
        elif status_code > 403: 
            if retry == True:
                # try once without the session ID
                msg = f"PaDS login returned {status_code}. Trying without session id."
                logger.error(msg)
                pads_session_info = authserver_login(username=username, password=password, client_id=client_id, retry=False)
            else:
                msg = f"Authorization System Issue. PaDS login returned {status_code}. Already retried (failed), or retry not selected."
                logger.error(msg)
                pads_session_info = models.PadsSessionInfo()
                pads_session_info.pads_status_response = status_code
                pads_session_info.pads_disposition = msg 
        else:
            try:
                pads_response = pads_response.json()
                pads_response = fix_pydantic_invalid_nones(pads_response)
                if isinstance(pads_response, str):
                    pads_session_info = models.PadsSessionInfo()
                    msg = f"Pads returned error string: {pads_response}"
                    logger.error(msg)
                else:
                    try:
                        pads_session_info = models.PadsSessionInfo(**pads_response)
                    except Exception as e:
                        msg = f"Pads return assignment error: {e}"
                        logger.error(msg)
                        pads_session_info = models.PadsSessionInfo()
            except Exception as e:
                logger.error(f"PaDS response processing error {e}")
                pads_session_info = models.PadsSessionInfo(**pads_session_info)
                pads_session_info.pads_status_response = status_code
                pads_session_info.pads_disposition = msg 
                
    return pads_session_info

def authserver_logout(session_id, request: Request=None, response: Response=None):
    ret_val = False
    if session_id is not None:
        if response is not None:
            response.delete_cookie(key=opasConfig.OPASSESSIONID,path="/",
                                   domain=localsecrets.COOKIE_DOMAIN)
        
        full_URL = base + f"/v1/Users/Logout/?SessionId={session_id}"
        response = requests.post(full_URL, headers={"Content-Type":"application/json"})
        if response.ok:
            ret_val = True
        else:
            logger.error(f"Error logging out for sessionId: {session_id} from PaDS: {response.json()}")
    else:
        logger.warning("No SessionId supplied.")

    return ret_val

def authserver_permission_check(session_id, doc_id, doc_year, reason_for_check=None):
    ret_val = False
    ret_resp = None
    if reason_for_check is None:
        logger.warning("fulltext_request info not supplied")
        
    full_URL = base + f"/v1/Permits?SessionId={session_id}&DocId={doc_id}&DocYear={doc_year}&ReasonForCheck={reason_for_check}"
    
    response = requests.get(full_URL)
    if response.status_code == 503:
        # PaDS down, fake it for now
        msg = f"Permits response error {e}. Temporarily return data."
        logger.error(msg)
        ret_resp = models.PadsPermitInfo(SessionId = session_id,
                                         DocID = doc_id,
                                         HasArchiveAccess=True, 
                                         HasCurrentAccess=False,
                                         Permit=True, 
                                         ReasonId=0, 
                                         StatusCode=200,
                                         ReasonStr="PaDS not responding"
        )
        
    try:
        ret_resp = response.json()
        ret_resp = models.PadsPermitInfo(**ret_resp)
        # returns 401 for a non-authenticated session
        ret_resp.StatusCode = response.status_code
        ret_val = ret_resp.Permit
        
    except Exception as e:
        msg = f"Permits response error {e}. Composing no access response."
        logger.error(msg)
        ret_val = False
        ret_resp = models.PadsPermitInfo(SessionId=session_id,
                                         DocId=doc_id,
                                         ReasonStr=msg)

    return ret_val, ret_resp      
        
def get_access_limitations(doc_id,
                           classification,
                           session_info,
                           year=None,
                           doi=None,
                           documentListItem: models.DocumentListItem=None,
                           fulltext_request:bool=None):
    """
    Based on the classification of the document (archive, current [embargoed],
       free, offsite), and the users permissions in session_info, determine whether
       this user has access to the full-text of the document, and fill out permissions
       in documentListItem (ret_val) structure for document doc_id
       
    """
    try:
        
        if documentListItem is not None:
            ret_val = documentListItem
        else:
            ret_val = models.AccessLimitations()
    
        ret_val.doi = doi
        ret_val.accessLimitedPubLink = None
        ret_val.accessLimited = True # no access...default, may be changed below.
        
        if session_info is None:
            logger.debug(f"Document permissions for {doc_id} -- no session info")
            ## not logged in; take the quickest way out.
            #ret_val.accessLimitedDescription = opasConfig.ACCESS_SUMMARY_FORSUBSCRIBERS 
            #ret_val.accessLimited = True
            #ret_val.accessLimitedReason = opasConfig.ACCESS_SUMMARY_DESCRIPTION + opasConfig.ACCESS_SUMMARY_FORSUBSCRIBERS
        
        if ret_val.doi is not None:
            publisherAccess = opasConfig.ACCESS_SUMMARY_PUBLISHER_INFO + opasConfig.ACCESS_SUMMARY_PUBLISHER_INFO_DOI_LINK % ret_val.doi
            # TODO: get the link we use to send users to publishers site when we don't have it, and no doi, and implement here.
            #       for now, just doi
            ret_val.accessLimitedPubLink = opasConfig.ACCESS_SUMMARY_PUBLISHER_INFO_DOI_LINK % ret_val.doi
        else:
            publisherAccess = ""
        
        if classification in (opasConfig.DOCUMENT_ACCESS_FREE):
            # free can be for anytone
            ret_val.accessLimitedDescription = opasConfig.ACCESSLIMITED_DESCRIPTION_FREE
            ret_val.accessLimited = False
            ret_val.accessLimitedCurrentContent = False
            #"This content is currently free to all users."
            ret_val.accessLimitedReason = opasConfig.ACCESSLIMITED_DESCRIPTION_FREE
            
        elif classification in (opasConfig.DOCUMENT_ACCESS_OFFSITE):
            ret_val.accessLimitedDescription = opasConfig.ACCESSLIMITED_DESCRIPTION_OFFSITE
            ret_val.accessLimited = True
            ret_val.accessLimitedCurrentContent = False
            #"This content is currently free to all users."
            ret_val.accessLimitedReason = opasConfig.ACCESS_SUMMARY_DESCRIPTION + opasConfig.ACCESS_SUMMARY_EMBARGOED + publisherAccess # limited...get it elsewhere
    
        elif classification in (opasConfig.DOCUMENT_ACCESS_EMBARGOED): # PEPCurrent
            ret_val.accessLimitedDescription = opasConfig.ACCESS_SUMMARY_EMBARGOED
            ret_val.accessLimitedCurrentContent = True
            ret_val.accessLimitedReason = opasConfig.ACCESS_SUMMARY_DESCRIPTION + opasConfig.ACCESS_SUMMARY_EMBARGOED + publisherAccess # limited...get it elsewhere
            if session_info is not None:
                try:
                    if session_info.authorized_pepcurrent:
                        ret_val.accessLimited = False # you can access it
                        ret_val.accessLimitedCurrentContent = True # true, this is current content,
                        # "This current content is available for you to access"
                        ret_val.accessLimitedReason = opasConfig.ACCESSLIMITED_DESCRIPTION_CURRENT_CONTENT_AVAILABLE 
                except Exception as e:
                    logger.error(f"PEPCurrent document error checking permission: {e}")
            else:
                logger.debug("No session info provided to assess current document authorization")
        elif classification in (opasConfig.DOCUMENT_ACCESS_ARCHIVE):
            ret_val.accessLimitedDescription = opasConfig.ACCESS_SUMMARY_FORSUBSCRIBERS 
            ret_val.accessLimited = True
            ret_val.accessLimitedReason = opasConfig.ACCESS_SUMMARY_DESCRIPTION + opasConfig.ACCESS_SUMMARY_FORSUBSCRIBERS
            if session_info is not None:
                try:
                    if session_info.authorized_peparchive:
                        ret_val.accessLimited = False
                        ret_val.accessLimitedCurrentContent = False
                        # "This content is available for you to access"
                        ret_val.accessLimitedReason = opasConfig.ACCESSLIMITED_DESCRIPTION_AVAILABLE
                        logger.debug("Optimization - session info used to authorize PEPArchive document")
                except Exception as e:
                    logger.error(f"PEPArchive document error checking permission: {e}")
            else:
                logger.debug("No session info provided to assess archive document authorization")
        else:
            logger.error(f"Unknown classification: {classification}")
        
        # We COULD check the session_id in PADS here with the art_id and year, for EVERY return!
        #  would it be slow?  Certainly for more than a dozen records, might...this is just for one instance though.
        # print (f"SessionID {session_info.session_id}, classificaton: {ret_val.accessLimited} and client_session: {session_info.api_client_session}")
        
        if session_info is not None:
            try:                   
                # always check for a full-text request so PaDS can track them.
                # since we don't really always know about authentication, we need to check all requests that are otherwise rejected.
                # if (session_info.confirmed_unauthenticated == False and (ret_val.accessLimited == True or fulltext_request == True)): # and session_info.api_client_session and session_info.api_client_id in PADS_BASED_CLIENT_IDS:
                # TODO: This is temp...just check as long as there is a session and full-text is requested
                #if session_info.session_id is not None and fulltext_request == True:
                if (session_info.confirmed_unauthenticated == False # Must be authenticated for this check
                    and (ret_val.accessLimited == True # if it's marked limited, then may need to check, it might be first one
                         or fulltext_request == True)): # or whenever full-text is requested.
                    # and session_info.api_client_session and session_info.api_client_id in PADS_BASED_CLIENT_IDS:
                    if fulltext_request:
                        reason_for_check = opasConfig.AUTH_DOCUMENT_VIEW_REQUEST
                    else:
                        reason_for_check = opasConfig.AUTH_ABSTRACT_VIEW_REQUEST
    
                    logger.debug(f"Sending permit request for {session_info.session_id}")
                    try:
                        authorized, resp = authserver_permission_check(session_id=session_info.session_id,
                                                                 doc_id=doc_id,
                                                                 doc_year=year,
                                                                 reason_for_check=reason_for_check)
                    except Exception as e:
                        # PaDS could be down, local development
                        logger.error(f"PaDS Access Exception: {e}")
                        if localsecrets.BASEURL == "development.org:9100":
                            resp = models.PadsPermitInfo(Permit=True, HasArchiveAccess=True, HasCurrentAccess=True)
                            # so it doesn't have to check this later
                            session_info.authorized_peparchive = True
                            session_info.authorized_pepcurrent = True
                            authorized = True
                        else:
                            session_info.authorized_peparchive = False
                            session_info.authorized_pepcurrent = False
                            authorized = False
                            resp = models.PadsPermitInfo(Permit=False, HasArchiveAccess=False, HasCurrentAccess=False)
                            
    
                    finally:
                        # if this is True, then we can stop asking this time
                        if resp.StatusCode == httpCodes.HTTP_401_UNAUTHORIZED:
                            logger.info(f"Document {doc_id} unavailable.  Reason: {ret_val.accessLimitedDescription}. No more checks needed this set")
                            session_info.confirmed_unauthenticated = True # now we can exit
                        else:
                            # if this is True, then as long as session_info is valid, it won't need to check again
                            # if accessLimited is ever True again, e.g., now a different type of document, it will check again.
                            # should markedly decrease the number of calls to PaDS to check.
                            # check for conflicts
                            if session_info.authorized_peparchive == True and resp.HasArchiveAccess == False:
                                logger.error(f"Permission Conflict: session {session_info.session_id} PEPArchive authorized; PaDS says No. PaDS message: {resp.ReasonStr} ")
                                
                            if resp.HasArchiveAccess == True:
                                session_info.authorized_peparchive = True
                                ret_val.accessLimited = False
                            
                            if resp.HasCurrentAccess == True:
                                session_info.authorized_pepcurrent = True
                                ret_val.accessLimitedCurrentContent = False
                        
                            if fulltext_request and authorized:
                                # let's make sure we know about this user.
                                if session_info.user_id == opasConfig.USER_NOT_LOGGED_IN_NAME:
                                    # We got this far, We need to find out who this is
                                    logger.info(f"Full-text request {doc_id}, authorized, but user not logged in {session_info.api_client_id}")
                                    pads_user_info = get_authserver_session_userinfo(session_info.session_id, session_info.api_client_id)
                                    if pads_user_info is not None:
                                        session_info.user_id = pads_user_info.UserId
                                        session_info.username = pads_user_info.UserName
                                        session_info.user_type = pads_user_info.UserType # TODO - Add this to session table
                                        # session_info.session_expires_time = ?
                                        ocd = opasCentralDBLib.opasCentralDB()
                                        ocd.update_session(session_info.session_id,
                                                           userID=session_info.user_id,
                                                           username=session_info.username, 
                                                           authenticated=1,
                                                           authorized_peparchive=1 if session_info.authorized_peparchive == True else 0,
                                                           authorized_pepcurrent=1 if session_info.authorized_pepcurrent == True else 0,
                                                           session_end=session_info.session_expires_time,
                                                           api_client_id=session_info.api_client_id
                                                           )
                                        
                            if authorized:
                                # "This content is available for you to access"
                                ret_val.accessLimitedDescription = opasConfig.ACCESSLIMITED_DESCRIPTION_AVAILABLE 
                                ret_val.accessLimited = False
                                #documentListItem.accessLimitedCurrentContent = False
                                # "This content is available for you to access"
                                ret_val.accessLimitedReason = opasConfig.ACCESSLIMITED_DESCRIPTION_AVAILABLE 
                                logger.info(f"Document {doc_id} available.  Opas Reason: {ret_val.accessLimitedDescription}")
                            else:
                                ret_val.accessLimited = True
                                if classification in (opasConfig.DOCUMENT_ACCESS_EMBARGOED):
                                    ret_val.accessLimitedReason
                                logger.info(f"Document {doc_id} unavailable.  Pads Reason: {resp.ReasonStr} Opas Reason: {ret_val.accessLimitedDescription}") # limited...get it elsewhere
                else:
                    # not full-text OR (not authenticated or accessLimited==False)
                    logger.debug(f"No PaDS check needed (no access).  Document {doc_id} accessLimited: {ret_val.accessLimited}. Unauthent: {session_info.confirmed_unauthenticated}")
        
            except Exception as e:
                logger.error(f"Issue checking document permission. Possibly not logged in {e}")
                pass # can't be checked, will be unauthorized.

    except Exception as e:
        logger.error(f"General exception {e} trying ascertain access limitations.")
        
    return ret_val

# ##################################################################################################################################################
#
#  LOCAL ROUTUNES
#
# ##################################################################################################################################################
def get_pads_session_info(session_id=None, client_id=opasConfig.NO_CLIENT_ID, retry=True):
    """
    Get the PaDS session model, and get a new session ID from the auth server if needed 
    """
    msg = ""
    
    if session_id is not None:
        full_URL = base + f"/v1/Authenticate/IP/" + f"?SessionID={session_id}"
    else:
        full_URL = base + f"/v1/Authenticate/IP/"

    try:
        pads_session_info = requests.get(full_URL)
    except Exception as e:
        logger.error(f"PaDS Authorization server not available. {e}")
        pads_session_info = models.PadsSessionInfo()
    else:
        status_code = pads_session_info.status_code # save it for a bit (we replace pads_session_info below)
        if status_code > 403: # e.g., (httpCodes.HTTP_500_INTERNAL_SERVER_ERROR, httpCodes.HTTP_503_SERVICE_UNAVAILABLE):
            # try once without the session ID
            if retry == True:
                pads_session_info = get_pads_session_info(client_id=client_id, retry=False)
                pads_session_info.pads_status_response = status_code
            else:
                msg = f"PaDS error {pads_session_info.status_code}"
                logger.error(msg)
                pads_session_info = models.PadsSessionInfo()
                pads_session_info.pads_status_response = status_code
                pads_session_info.pads_disposition = msg 
        else:
            try:
                pads_session_info = pads_session_info.json()
                pads_session_info = fix_pydantic_invalid_nones(pads_session_info)
                pads_session_info = models.PadsSessionInfo(**pads_session_info)
                pads_session_info.pads_status_response = status_code
            except Exception as e:
                msg = f"PaDS response processing error {e}"
                logger.error(msg)
                pads_session_info = models.PadsSessionInfo(**pads_session_info)
                pads_session_info.pads_status_response = status_code
                pads_session_info.pads_disposition = msg 

    return pads_session_info

if __name__ == "__main__":
    import doctest
    import sys
    
    print (40*"*", "opasDocPermissionsTests", 40*"*")
    print (f"Running in Python {sys.version_info[0]}.{sys.version_info[1]}")
   
    logger = logging.getLogger(__name__)
    ch = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(name)s %(lineno)d - %(levelname)s %(message)s')    
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    doctest.testmod(optionflags=doctest.ELLIPSIS|doctest.NORMALIZE_WHITESPACE)
    print ("Fini. Tests complete.")