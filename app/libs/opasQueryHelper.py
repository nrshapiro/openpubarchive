#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=C0321,C0103,C0301,E1101,C0303,E1004,C0330,R0915,R0914,W0703,C0326

"""
opasQueryHelper

This library is meant to hold parsing and other functions which support query translation to Solr

2020.0530.1 - Doc Test updates
2020.0416.1 - Sort fixes, new viewcount options
2019.1205.1 - First version

"""
__author__      = "Neil R. Shapiro"
__copyright__   = "Copyright 2019-2021, Psychoanalytic Electronic Publishing"
__license__     = "Apache 2.0"
__version__     = "2020.1013.1"
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
from configLib.opasCoreConfig import solr_docs, solr_authors, solr_gloss, solr_docs_term_search, solr_authors_term_search
import opasConfig 
from opasConfig import KEY_SEARCH_FIELD, KEY_SEARCH_SMARTSEARCH, KEY_SEARCH_VALUE
from configLib.opasCoreConfig import EXTENDED_CORES

import models
import opasCentralDBLib
import schemaMap
import opasGenSupportLib as opasgenlib
import opasXMLHelper as opasxmllib
import opasDocPermissions as opasDocPerm

count_anchors = 0

import smartsearch

sourceDB = opasCentralDBLib.SourceInfoDB()
ocd = opasCentralDBLib.opasCentralDB()
pat_prefix_amps = re.compile("^\s*&& ")

cores  = {
    "docs": solr_docs,
    "authors": solr_authors,
}

#-----------------------------------------------------------------------------
def get_base_article_info_by_id(art_id):
    from opasPySolrLib import search_text
    
    documentList, ret_status = search_text(query=f"art_id:{art_id}", 
                                           limit=1,
                                           abstract_requested=False,
                                           full_text_requested=False
                                           )

    try:
        ret_val = documentListItem = documentList.documentList.responseSet[0]
    except Exception as e:
        logger.warning(f"Error getting article {art_id} by id: {e}")
        ret_val = None
        
    return ret_val

#-----------------------------------------------------------------------------
def is_empty(arg):
    if arg is None or arg == "":
        return True
    else:
        return False

#-----------------------------------------------------------------------------
def get_field_data_len(arg):
    syn = r"(?P<field>[^\:]*?)\:(?P<rest>.*)"
    m = re.match(syn, arg, flags=re.IGNORECASE)
    if m:
        mgr = m.group("rest")
        ret_val = len(mgr)
    else:
        mgr = ""
        ret_val = len(arg)
        
    #print (f"Field Len: {ret_val} / {mgr} / {arg}")
    return ret_val

#-----------------------------------------------------------------------------
def check_search_args(**kwargs):
    ret_val = {}
    errors = False
    for kw in kwargs:
        #print(kw, ":", kwargs[kw])
        arg = kwargs[kw]
        if arg is not None and "text" in kw:
            # check query and remove proximity if boolean
            try:
                if are_brackets_balanced(arg):
                    ret_val[kw] = remove_proximity_around_booleans(arg)
                    #print (f"After remove_proximity: {ret_val[kw]}")
                else:
                    #print (f"After remove_proximity: {ret_val[kw]}")
                    ret_val[kw] = 422
                    errors = True
            except Exception as e:
                logger.error(f"fulltext cleanup error {e}")
                print (f"Cleanup error: {e}")
                errors = True
        else: # for now, just return.  Later more checks
            ret_val[kw] = arg
            
    return errors, ret_val        

def cleanup_spaces_within_parens(arg):
    ret_val = arg
    try:
        # clean up spaces after open paren and before close
        ret_val = re.sub("\(\s+", "(", ret_val)
        ret_val = re.sub("\s+\)", ")", ret_val)
    except Exception as e:
        logger.error(f"Data conversion error: {e}")

    return ret_val    
#-----------------------------------------------------------------------------
def cleanup_solr_query(solrquery):
    """
    Clean up full solr query, which may have multiple clauses connected via booleans

    Clean up whitespace and extra symbols that happen when building up query or solr query filter
 
    >>> cleanup_solr_query('body_xml:"Evenly Suspended Attention"~25 && body_xml:tuckett')   
    'body_xml:"Evenly Suspended Attention"~25 && body_xml:tuckett'
    
    >>> cleanup_solr_query('body_xml:"Even and Attention"~25 && body_xml:tuckett')   
    'body_xml:(Even && Attention) && body_xml:tuckett'
    
    """
    ret_val = solrquery.strip()
    ret_val = ' '.join(ret_val.split()) #solrquery = re.sub("\s+", " ", solrquery)
    
    # clean up spaces after open paren and before close
    ret_val = cleanup_spaces_within_parens(ret_val)
    
    if ret_val is not None:
        # no need to start with '*:* && '.  Remove it.
        ret_val = ret_val.replace("*:* && ", "") # Typical instance, remove it
        ret_val = ret_val.replace("*:* {", "{")  # Remove if it's before a solr join for level 2 queries
        ret_val = pat_prefix_amps.sub("", ret_val)

    ret_val = re.sub("\s+(AND)\s+", " && ", ret_val, flags=re.IGNORECASE)
    ret_val = re.sub("\s+(OR)\s+", " || ", ret_val, flags=re.IGNORECASE)
    ret_val = re.sub("\s+(NOT)\s+", " NOT ", ret_val, flags=re.IGNORECASE)
    ret_val = remove_proximity_around_booleans(ret_val)

    # one last cleaning, watch for && *:*
    ret_val = ret_val.replace(" && *:*", "")
    
    
    return ret_val

#-----------------------------------------------------------------------------
def strip_outer_matching_chars(s, outer_char):
    """
    If a string has the same characters wrapped around it, remove them.
    Make sure the pair match.
    """
    s = s.strip()
    if (s[0] == s[-1]) and s.startswith(outer_char):
        return s[1:-1]
    return s
#-----------------------------------------------------------------------------
def search_qualifiers(searchstr, field_label, field_thesaurus=None, paragraph_len=25):
    """
    See if the searchstr has a special prefix qualifying the search
    
    [5]P> = within 5 paragraphs, P> (default one paragraph, paragraph_len)
    [5]W> = within 5 words
    T>    = Use Thesaurus 
    
    """
    ret_val = False # if there's no qualifier
    search_specs = None
    search_qual = "^\s*(?P<arg>[0-9]{0,3})(?P<op>[PWT])\s(?P<spec>.*)"
    m = re.match(search_qual, searchstr, re.IGNORECASE)
    if m:
        ret_val = True
        op = m.group("op").upper()
        spec = m.group("spec")
        arg = m.group("arg")
        if arg == "":
            arg = 1
        else:
            arg = int(arg)

        if op == "P":
            #  paragraph proximity
            distance = arg * paragraph_len
            search_specs = f'{field_label}:"{spec}"~{distance}'
        elif op == "W":
            distance = arg
            search_specs = f'{field_label}:"{spec}"~{distance}'
        elif op == "T":
            distance = arg
            # Thesaurus
            if field_thesaurus is not None:
                search_specs = f'{field_thesaurus}:"{spec}"~{distance}'
        else:
            raise Exception("Programming Error - RE Specification")
            
    return ret_val, search_specs

#-----------------------------------------------------------------------------
def comma_sep_list_to_simple_bool(termlist_str, boolpred="||"):
    """
    Take a comma separated term list or boolean list and change to a
    bool type query list using the single boolpred as connecting term (e.g., for solr)
    
    Really meant for comma separated lists, but in case use input has
    boolean connectors, it can remove those.
    
    **IMPORTANT: if your user is going to be entering boolean phrases, with various
      logical connectors, you should not be calling this for processing the list
    
    >>> a = "EN, IT,  FR"
    >>> comma_sep_list_to_simple_bool(a)
    'EN || IT || FR'
    
    >>> a = "EN AND IT OR  FR NOT EX"
    >>> comma_sep_list_to_simple_bool(a)
    'EN || IT || FR || EX'

    """
    # split it
    term_list = re.split("\W+", termlist_str)
    term_list = [val for val in term_list if val not in ("NOT", "OR", "AND")] # list(filter(("OR").__ne__, term_list))
    ret_val = f" {boolpred} ".join(term_list)
    return ret_val
#-----------------------------------------------------------------------------
#def termlist_to_doubleamp_query(termlist_str, field=None):
    #"""
    #Take a comma separated term list and change to a
    #(double ampersand) type query term (e.g., for solr)
    
    #>>> a = "tuckett, dav"
    #>>> termlist_to_doubleamp_query(a)
    #'tuckett && dav'
    #>>> termlist_to_doubleamp_query(a, field="art_authors_ngrm")
    #'art_authors_ngrm:tuckett && art_authors_ngrm:dav'

    #"""
    ## in case it's in quotes in the string
    #termlist_str = termlist_str.replace('"', '')
    ## split it
    #name_list = re.split("\W+", termlist_str)
    ## if a field or function is supplied, use it
    #if field is not None:
        #name_list = [f"art_authors_ngrm:{x}"
                     #for x in name_list if len(x) > 0]
    #else:
        #name_list = [f"{x}" for x in name_list]
        
    #ret_val = " && ".join(name_list)
    #return ret_val

def parse_to_query_term_list(str_query):
    """
    Take a string and parse the field names and field data clauses to q list of
      SolrQueryTerms
      
      NOTE: this is only used by testSearchSyntax to produce term_lists!
      
    >>> str = "dreams_xml:mother and father and authors:David Tuckett and Nadine Levinson"
    >>> parse_to_query_term_list(str)
    [SolrQueryTerm(connector=' && ', subClause=[], field='dreams_xml', words='mother && father', parent=None, synonyms=False, synonyms_suffix='_syn'), SolrQueryTerm(connector='AND', subClause=[], field='authors', words='David Tuckett && Nadine Levinson', parent=None, synonyms=False, synonyms_suffix='_syn')]

    >>> str = "dreams_xml:(mother and father)"
    >>> parse_to_query_term_list(str)
    [SolrQueryTerm(connector=' && ', subClause=[], field='dreams_xml', words='(mother && father)', parent=None, synonyms=False, synonyms_suffix='_syn')]
    
      
    """
    field_splitter = "([a-z\_]+\:)"
    ends_in_connector = "\s(AND|OR)\s?$"
    split_query = re.split(field_splitter, str_query, flags=re.IGNORECASE)
    split_query = list(filter(None, split_query)) # get rid of empty strings
    term_list = []
    count = 0
    temp = models.SolrQueryTerm()
    for n in split_query:
        if n[-1] == ":":
            # this is a field
            temp.field = n[0:-1]
        else: # data
            data_split = re.split(ends_in_connector, n, flags=re.IGNORECASE)
            data_split = list(filter(None, data_split))
            temp.words = data_split[0]
            # ok, we have the data, append the node
            temp.words = cleanup_solr_query(temp.words)
            term_list.append(temp)
            # make a new node
            temp = models.SolrQueryTerm()
            # add the connector if there is one
            if len(data_split) > 1:
                temp.connector = data_split[-1].upper()
            count += 1
            
    logger.info(term_list)
    return term_list
    
#-----------------------------------------------------------------------------
class QueryTextToSolr(): 
    """
    This is a simple regex based word and phrase entry parser, intended to handle
      words and quoted phrases separated by ' and ' or ' or '.
      
    Syntax allowed:
      space separated list of words or phrases
      space separated list of words or phrases connected by AND or OR (with spaces as separation)
      negated words or phrases in quotes in above, where word or phrase prefixed by ^
      phrase in quotes followed by ~ and a number (for word proximity)
      parentheses for grouping the above
    
    >>> qs = QueryTextToSolr()
    >>> qs.boolConnectorsToSymbols("a and band")
    'a && band'
    
    >>> qs.markup("dog -mouse", field_label="text_xml")
    'text_xml:(dog -mouse)'
    
    >>> qs.markup("[* TO 2010]", field_label="year")
    'year:[* TO 2010]'
    
    >>> qs.markup("year:[* TO 2010]")
    'year:[* TO 2010]'

    >>> qs.markup("[2010]", field_label="year")
    'year:[2010]'
    
    >>> qs.markup("dog and cat or mouse", field_label="text_xml")
    'text_xml:(dog && cat || mouse)'
    
    >>> qs.markup("'dog and cat or mouse'", field_label="text_xml")
    "text_xml:'dog and cat or mouse'"
    
    
    """
    def __init__(self):
        regex_token_quoted =  "[\^]?[\'\"][^\'\"]+[\'\"]"
        regex_token_word = "(?P<word>[^\|\^\&\(\"\'\s)]+)"

        self.counter = 0
        self.token_quoted = re.compile(regex_token_quoted, re.IGNORECASE)
        self.token_or = re.compile("\s+OR\s+", re.IGNORECASE)
        self.token_and = re.compile("\s+AND\s+", re.IGNORECASE)
        self.token_not = re.compile("\s+not\s+")
        
        self.token_word = re.compile(regex_token_word, re.IGNORECASE)
        self.token_implied_and = re.compile("(^&&)+\s", re.IGNORECASE) 

    #-----------------------------------------------------------------------------
    def wrap_clauses(self, solrquery):
        # split by OR clauses
        ret_val = solrquery
        if isinstance(solrquery, str):
            try:
                ret_val = ret_val.strip()
                if "||" in solrquery:
                    ret_val = ret_val.split(" || ")
                    ret_val = ["(" + x + ")" for x in ret_val]
                    ret_val = " || ".join(ret_val)
                
                if "&&" in solrquery:
                    ret_val = ret_val.split(" && ")
                    ret_val = ["(" + x + ")" for x in ret_val]
                    ret_val = " && ".join(ret_val)
    
            except Exception as e:
                logger.error(f"Processing error: {e}")
        return ret_val    

    def boolConnectorsToSymbols(self, str_input):
        ret_val = str_input
        if isinstance(str_input, str):
            if opasgenlib.not_empty(ret_val) and not opasgenlib.in_quotes(ret_val):
                ret_val = self.token_or.sub(" || ", ret_val)
                ret_val = self.token_and.sub(" && ", ret_val)
                ret_val = self.token_not.sub(" NOT ", ret_val) # upper case a must
        
        return ret_val
        
    def markup(self, str_input, field_label=None, field_thesaurus=None, quoted=False):
        
        bordered = opasgenlib.in_parens(str_input) or opasgenlib.in_quotes(str_input) or opasgenlib.one_term(str_input) or opasgenlib.in_brackets(str_input)

        if quoted == False:
            str_input_mod = self.boolConnectorsToSymbols(str_input)
            # str_input_mod = self.wrap_clauses(str_input_mod)
            if field_label is not None:
                if not bordered: 
                    ret_val = f"{field_label}:({str_input_mod})"
                else:
                    ret_val = f"{field_label}:{str_input_mod}"
            else:
                ret_val = f"{str_input_mod}"
        else:
            if field_label is not None:
                if not bordered:
                    ret_val = self.boolConnectorsToSymbols(f'{field_label}:"({str_input})"')
                else:
                    ret_val = self.boolConnectorsToSymbols(f'{field_label}:"{str_input}"')
            else:
                ret_val = self.boolConnectorsToSymbols(f'"{str_input}"')

        # watch for - inside parens
        ret_val = re.sub(r"\(\-([A-Z]+)", "-(\g<1>", ret_val)
        ret_val = re.sub("([A-Z]\.)([A-Z])", "\g<1> \g<2>", ret_val)

        # ret_val = self.handle_solr_not(ret_val)

        return ret_val

    def handle_solr_not(self, searchstr):
        
        ret_val = re.split("[&|]{2,2}", searchstr)
        for n in ret_val:
            n
        m = re.match(r"([a-z]+:)([\(\s])(\-)([a-z]+[\)\s])", ret_val, flags=re.IGNORECASE)
        if m:
            ret_val = f"-{m.group(1)}{m.group(2)}{m.group(4)}"
            
        return ret_val
#-----------------------------------------------------------------------------
def year_parser_support(year_arg):

    ret_val = ""
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
            if option is None and separator is None:
                search_clause = f" art_year_int:{year_arg} "
            elif option == "=" and separator is None:
                search_clause = f" art_year_int:{year_arg} "
            elif separator == "-":
                # between
                # find endyear by parsing
                if start is None:
                    start = "*"
                if end is None:
                    end = "*"
                search_clause = f" art_year_int:[{start} TO {end}] "
            elif option == ">":
                # greater
                if start is None and end is not None:
                    start = end # they put > in start rather than end.
                else:
                    start = int(start) + 1

                search_clause = f" art_year_int:[{start} TO *] "
            elif option == "<":
                # less than
                if end is None and start is not None:
                    end = start  
                    end = int(end) - 1
                search_clause = f" art_year_int:[* TO {end}] "

            ret_val = search_clause
        
        return ret_val    

def orclause_paren_wrapper(search_clause):
    subclauses = re.split(" OR ", search_clause, flags=re.IGNORECASE)
    ret_val = ""
    for n in subclauses:
        if n != "":
            if ret_val != "":
                ret_val += f" || ({n})"
            else:
                ret_val += f"({n})"    

    return ret_val

def year_arg_parser(year_arg):
    """
    Look for full start/end year ranges submitted in a single field.
    Returns with Solr field name and proper syntax
    
    For example:
        >1977
        <1990
        1980-1990
        1970

    >>> year_arg_parser("=1955")
    '&& ( art_year_int:=1955 )'
    >>> year_arg_parser("1970")
    '&& ( art_year_int:1970 )'
    >>> year_arg_parser("-1990")
    '&& ( art_year_int:[* TO 1990] )'
    >>> year_arg_parser("1980-")
    '&& ( art_year_int:[1980 TO *] )'
    >>> year_arg_parser("1980-1980")
    '&& ( art_year_int:[1980 TO 1980] )'
    >>> year_arg_parser(">1977")
    '&& ( art_year_int:[1978 TO *] )'
    >>> year_arg_parser("<1990")
    '&& ( art_year_int:[* TO 1989] )'
    >>> year_arg_parser("1980-1990")
    '&& ( art_year_int:[1980 TO 1990] )'
    """
    ret_val = None
    #  see if it's bool claused
    bools = re.split(" OR ", year_arg, flags=re.IGNORECASE)
    clause = ""
    for n in bools:
        if n != "":
            year_n = year_parser_support(n)
            if year_n is not None:
                if clause != "" and year_n != "":
                    clause += f" || {year_n}"
                else:
                    clause += f"{year_n}"

    # if there's an || in here, you need parens to give it precedence on the &&
    if clause != "":
        ret_val = f"&& ({clause})"
    else:
        ret_val = ""

    return ret_val
                   
    
def get_term_list_spec(termlist):
    """
    Process termlists with recursion capabilities
    
    """
    ret_val = ""
    for q_term in termlist:
        try:
            boolean_connector = q_term.connector
        except:
            boolean_connector = ""

        q_term_sublist = []
        try:
            q_term_sublist = q_term.subClause
        except:
            q_term_sublist = []
            
        if q_term_sublist != []:
            ret_val += f"{boolean_connector} ({get_term_list_spec(q_term_sublist)})"
        else:
            if q_term.field is None:
                use_field = "text"
            else:
                use_field = q_term.field
    
            if q_term.synonyms:
                use_field = use_field + q_term.synonyms_suffix
            
            if use_field is not None and opasgenlib.not_empty(q_term.words):
                sub_clause = f"{use_field}:({q_term.words})"
            else:
                if opasgenlib.not_empty(q_term.words):
                    sub_clause = f"({q_term.words})"
                else:
                    sub_clause = ""
            if ret_val == "":
                ret_val = f"{sub_clause} "
            else:
                ret_val += f" {boolean_connector} {sub_clause}"

    return ret_val        

#def dequote(fulltext1):
    #"""
    #>>> test1='body_xml:("Evenly Suspended Attention"~25) && body_xml:(tuckett)'
    #>>> dequote(test1)
    #' && body_xml:("Evenly Suspended Attention"~25) && body_xml:(tuckett)'
    
    #>>> test2 = 'text:("Evenly Suspended Attention"~25) && body_xml:(tuckett) && body_xml:("basic || principles"~25)'
    #>>> dequote(test2)
    #' && text:("Evenly Suspended Attention"~25) && body_xml:(tuckett) && body_xml:(basic || principles)'
    
    #>>> test3 = 'text:("Evenly Suspended Attention"~25) && body_xml:(tuckett) && body_xml:("basic OR principles"~25)'
    #>>> dequote(test3)
    #' && text:("Evenly Suspended Attention"~25) && body_xml:(tuckett) && body_xml:(basic || principles)'
    
    #"""
    #quote_wrapper = '\s*(.*\:)?\(\"(.*)\"(~[1-9][0-9]*)\)|\s*(\&\&)?\s*(.*\:)?\((.*)\)'
    
    #clauses = fulltext1.split(" && ")
    #items = []
    #for clause in clauses:
        ## print (f"Clause:{clause}")
        #m = re.findall(quote_wrapper, clause, flags=re.I)
        #for n in m:
            #items.append([x for x in n if len(x) > 0 and x != "&&"])
        ## print (items)
    
    #new_search = ""
    #for item in items:
        #m = re.search("\&\&|\|\||\sAND\s|\sOR\s", item[1], flags=re.I)
        #if m is not None:
            #new_search += f' && {item[0]}({item[1]})'
        #else:
            #try:
                #new_search += f' && {item[0]}("{item[1]}"{item[2]})'
            #except Exception as e:
                #logger.warning (f"Dequote Exception {e}")               

    ## print (f"New Search: {new_search[4:]}")
    #return new_search       

def remove_proximity_around_booleans(query_str):
    """
    Clients like PEP-Web (Gavant) send fulltext1 as a proximity string.
    This removes the proximity if there's a boolean inside.
    We could have the client "not do that", but it's actually easier to
    remove than to parse and add.
    
    >>> a = '(article_xml:"dog AND cat"~25 AND body:"quick fox"~25) OR title:fox'
    >>> remove_proximity_around_booleans(a)
    '(article_xml:(dog AND cat) AND body:"quick fox"~25) OR title:fox'

    >>> a = 'body_xml:"Even and Attention"~25 && body_xml:tuckett'
    >>> remove_proximity_around_booleans(a)
    'body_xml:(Even and Attention) && body_xml:tuckett'
    
    """
    srch_ptn = r'\"([A-z\s0-9\!\@\*\~\-\&\|\[\]]+)\"~25'
    changes = False
    while 1:
        m = re.search(srch_ptn, query_str)
        if m is not None:
            # does it have a boolean, a quote, or a bracket (range)?
            n = re.search(r"\s(AND|OR|NOT|\&\&|\|\|)\s|([\"\[\']])", m.group(1), flags=re.IGNORECASE)
            # if it's not None, then this is not a proximity match
            if n is not None:
                query_str = re.subn(srch_ptn, r'(\1)', query_str, 1)[0]
            else: # change it so it doesn't match next loop iter
                query_str = re.subn(srch_ptn, r'"\1"~26', query_str, 1)[0]
                changes = True
        else:
            if changes:
                # change proximity ranges back
                query_str = re.sub("~26", "~25", query_str)
            break
        
    return query_str

def are_brackets_balanced(expr):
    """
    Checks to see if there are parens or brackets that are unbalanced
    
    """
    stack = [] 

    # Traversing the Expression 
    for char in expr: 
        if char in ["(", "{", "["]: 
            # Push the element in the stack 
            stack.append(char) 
        elif char in [")", "}", "]"]: 
            # IF current character is not opening 
            # bracket, then it must be closing. 
            # So stack cannot be empty at this point. 
            if not stack: 
                return False
            current_char = stack.pop() 
            if current_char == '(': 
                if char != ")": 
                    return False
            if current_char == '{': 
                if char != "}": 
                    return False
            if current_char == '[': 
                if char != "]": 
                    return False

    # Check Empty Stack 
    if stack: 
        return False
    return True


#---------------------------------------------------------------------------------------------------------
# function parse_search_query_parameters lets various endpoints like search, searchanalysis, and document, 
#   share this large parameter set.
# 
# IMPORTANT: Parameter names here must match the endpoint parameters since they are mapped in main using
# 
#            argdict = dict(parse.parse_qsl(parse.urlsplit(search).query))
#            solr_query_params = opasQueryHelper.parse_search_query_parameters(**argdict)
# and then resubmitted to solr for such things as document retrieval with hits in context marked.
# 
# Example:
#    http://development.org:9100/v2/Documents/Document/JCP.001.0246A/?return_format=HTML&search=?fulltext1=%22Evenly%20Suspended%20Attention%22~25&viewperiod=4&formatrequested=HTML&highlightlimit=5&facetmincount=1&facetlimit=15&sort=score%20desc&limit=15
#
# NOTE: 2020-12-20
#       Since this is at least in one case called with **args from the caller, the args must match the callers args.
#       See main.py:
#           solr_query_params = opasQueryHelper.parse_search_query_parameters(**argdict)
# 
def parse_search_query_parameters(search=None,             # url based parameters, e.g., from previous search to be parsed
                                  # model based query specification, allows full specification 
                                  # of words/thes in request body, component at a time, per model
                                  solrQueryTermList=None,
                                  # parameter based options
                                  fulltext1=None,          # term, phrases, and boolean connectors with optional fields for full-text search
                                  smarttext=None,          # experimental detection of search parameters
                                  paratext=None,           # search paragraphs as child of scope
                                  parascope=None,          # parent_tag of the para, i.e., scope of the para ()
                                  art_level: int=None,     # Level of record (top or child, as artlevel)
                                  like_this_id=None,       # for morelikethis
                                  cited_art_id=None,       # for who cited this
                                  similar_count:int=0,     # Turn on morelikethis for the set
                                  #solrSearchQ=None,       # the standard solr (advanced) query, overrides other query specs
                                  synonyms=False,          # global field synonyn flag (for all applicable fields)
                                  # these are all going to the filter query
                                  source_name=None,        # full name of journal or wildcarded
                                  source_code=None,        # series/source (e.g., journal code) or list of codes
                                  source_type=None,        # series source type, e.g., video, journal, book
                                  source_lang_code=None,   # source language code
                                  vol=None,                # match only this volume (integer)
                                  issue=None,              # match only this issue (integer)
                                  author=None,             # author last name, optional first, middle.  Wildcards permitted
                                  title=None,
                                  articletype=None,        # types of articles: article, abstract, announcement, commentary, errata, profile, report, or review
                                  datetype=None,           # not implemented
                                  startyear=None,          # can contain complete range syntax
                                  endyear=None,            # year only.
                                  citecount: str=None,     # can include both the count and the count period, e.g., 25 in 10 or 25 in ALL
                                  viewcount: str=None,     # can include both the count and the count period, e.g., 25 in last12months or 25 in ALL
                                  viewperiod=None,         # period to evaluate view count 0-4, 0:lastcalendaryear 1:lastweek 2:lastmonth, 3:last6months, 4:last12months
                                  facetfields=None,        # facetfields to return
                                  # sort field and direction
                                  facetmincount=None,
                                  facetlimit=None,
                                  facetoffset=0,
                                  facetspec: dict=None, 
                                  abstract_requested: bool=None,
                                  formatrequested:str=None,
                                  return_field_set=None,
                                  return_field_options=None, 
                                  sort=None,
                                  highlightlimit:int=None, # same as highlighting_max_snips, but matches params (REQUIRED TO MATCH!)
                                  extra_context_len=None,
                                  limit=None,
                                  offset=None, 
                                  # v1 parameters
                                  journal = None,
                                  req_url = None
                                  ):
    """
    This function parses various parameters in the api parameter and body to convert them
      to a Solr Query into model SolrQuerySpec.
      
    The optional parameter, solrQueryTermList holds a complete term by term query request,
    so field and synonym can vary.

        Sample:
            {   "artLevel": 2, 
                "query" :
                [
                    {
                        "field" : "para",
                        "words": "love",
                        "synonyms": "true",
                        "synonyms_suffix": "_syn"
                    },
                    {
                        "connector": "AND",
                        "field" : "para",
                        "words": "joy"
                    }
                ],
                "qfilter" : 
                [
                    {
                        "comment":"This example should produce the filter 'art_source_code:AOP && (art_year:1977 || art_year:2000)'",
                        "field" : "art_sourcecode",
                        "words": "AOP"
                    },
                    {
                        "field" : "art_year",
                        "words": "1977"
                    }
                ]
            }        

    >>> search = parse_search_query_parameters(journal="IJP", vol=57, author="Tuckett")
    >>> search.solrQuery.analyzeThis
    '(art_authors_text:(Tuckett) || art_authors_citation:(Tuckett))'
    
    """
    artLevel = 1 # Doc query, sets to 2 if clauses indicate child query
    search_q_prefix = ""
    search_result_explanation = None
    # IMPORTANT: 
    # These parameters need match the query line endpoint parameters for search, 
    #   but had been renamed, causing a problem.  So I've put the parameters back to the endpoint query parameter
    #   names, and converted them here to the new, cleaner, names.
    # highlighting_max_snips = highlightlimit
    format_requested = formatrequested   
    
    # watch for some explicit None parameters which override defaults
    if similar_count is None:
        similar_count = 0
    
    if facetoffset is None:
        facetoffset = 0

    if facetmincount is None:
        facetmincount = 1

    if facetspec is None:
        facetspec = {}

    if format_requested is None:
        format_requested = "HTML"

    if abstract_requested is None:
        abstract_requested = False

    if parascope is None:
        parascope = "doc"
        
    if isinstance(synonyms, str):
        logger.debug("Synonyms parameter should be bool, not str")
        if synonyms.lower() == "true":
            synonyms = True
        else:
            synonyms = False

    # always return SolrQueryOpts with SolrQuery
    if solrQueryTermList is not None:
        try:
            if solrQueryTermList.solrQueryOpts is not None:
                solrQueryOpts = solrQueryTermList.solrQueryOpts
            else: # initialize a new model
                solrQueryOpts = models.SolrQueryOpts()
        except Exception as e:
            solrQueryTermList = None
            solrQueryOpts = models.SolrQueryOpts()
            if isinstance(solrQueryTermList, str):
                logger.warning(f"solrQueryTermList must be a model {e}")
            else:
                logger.warning(f"solrQueryTermList error {e}")

        if solrQueryTermList.abstractReturn is not None and abstract_requested is None:
            abstract_requested = solrQueryTermList.abstractReturn

        if solrQueryTermList.facetFields is not None and facetfields is None:
            facetfields = solrQueryTermList.facetFields

        if solrQueryTermList.facetMinCount is not None and facetmincount is None:
            facetmincount = solrQueryTermList.facetMinCount

        if solrQueryTermList.facetSpec != {} and facetspec == {}:
            facetspec = solrQueryTermList.facetSpec

        if solrQueryTermList.returnFormat is not None and format_requested is None:
            format_requested = solrQueryTermList.returnFormat
    
        if solrQueryTermList.similarCount != 0 and similar_count == 0:
            similar_count = solrQueryTermList.similarCount
                
    else: # initialize a new model (qtermlist didn't supply and no other upper structure passed)
        solrQueryOpts = models.SolrQueryOpts()

    # Set up return structure
    solr_query_spec = \
        models.SolrQuerySpec(
                             core="pepwebdocs", # for now, this is tied to this core #TODO maybe change later
                             solrQuery = models.SolrQuery(),
                             solrQueryOpts=solrQueryOpts,
                             req_url=req_url
        )
    
    set_return_fields(solr_query_spec=solr_query_spec,
                      return_field_set=return_field_options,
                      return_field_options=return_field_options)

    if limit is not None:
        solr_query_spec.limit = limit

    if offset is not None:
        solr_query_spec.offset = offset
        
    if extra_context_len is not None:
        solr_query_spec.solrQueryOpts.hlFragsize = extra_context_len
           
    # v1 translation:
    if opasgenlib.not_empty(journal):
        source_code = journal

    if similar_count > 0:
        solr_query_spec.solrQueryOpts.moreLikeThisCount = similar_count
        # solr_query_spec.solrQueryOpts.moreLikeThis = True

    if like_this_id is not None:
        solr_query_spec.solrQuery.likeThisID = like_this_id
    
    # parent_tag is any parent of a child doc as stored in the schema child field parent_tag.  

    # initialize accumulated variables
    search_q = "*:* "  # solr main query q
    filter_q = "*:* "  # for solr filter fq
    analyze_this = ""  # search analysis
    search_analysis_term_list = [] # component terms for search analysis
    query_term_list = [] #  the terms themselves

    # Hold these for special view counts
    #vc_source_code = source_code # for view count query (if it can work this way)
    #vc_source_name = source_name # for view count query (if it can work this way)
    #vc_title = title # for view count query (if it can work this way)
    #vc_author = author # for view count query (if it can work this way)

    # used to remove prefix && added to queries.  
    # Could make it global to save a couple of CPU cycles, but I suspect it doesn't matter
    # and the function is cleaner this way.
    # this class can converts boolean operators AND/OR/NOT (case insensitive) to symbols ||, &&, ^
    # can do more but mainly using markup function for now.
    qparse = QueryTextToSolr()
    
    if sort is not None:
        s = sort
        mat = "(" + "|".join(opasConfig.PREDEFINED_SORTS.keys()) + ")"
        m = re.match(f"{mat}(\s(asc|desc))?", s, flags=re.IGNORECASE)
        if m: #  one of the predefined sorts was used.
            try:
                sort_key = m.group(1).lower()
                direction = m.group(2)
                if direction is None:
                    try:
                        direction = opasConfig.PREDEFINED_SORTS[sort_key][1]
                    except KeyError:
                        direction = "DESC" # default
                    except Exception as e:
                        logger.error(f"PREDEFINED_SORTS lookup error {e}")
                        direction = "DESC" # default
                
                sort = opasConfig.PREDEFINED_SORTS[sort_key][0].format(direction)
            except Exception as e:
                logger.warning(f"Predefined sort key {s} not found. Trying it directly against the database.")
        else:
            logger.debug(f"No match with predefined sort key; Passing sort through: {s}")
    #else:
        #sort = f"{opasConfig.DEFAULT_SOLR_SORT_FIELD} {opasConfig.DEFAULT_SOLR_SORT_DIRECTION}"

    if smarttext is not None:
        search_dict = smartsearch.smart_search(smarttext)
        # set up parameters as a solrQueryTermList to share that processing
        # solr_query_spec.solrQueryOpts.qOper = "OR"
        schema_field = search_dict.get("schema_field")
        limit = 0
        search_result_explanation = search_dict[KEY_SEARCH_SMARTSEARCH]
        if schema_field is not None:
            schema_value = search_dict.get("schema_value")
            if opasgenlib.not_empty(schema_value):
                if "'" in schema_value or '"' in schema_value:
                    search_q += f"&& {schema_field}:{schema_value} "
                else:
                    search_q += f"&& {schema_field}:({schema_value}) "
                limit = 1
        else:
            syntax = search_dict.get("syntax")
            if syntax is not None:
                if syntax == "solr" and search_q == "*:*":
                    query = search_dict.get("query")
                    if query is not None:
                        search_q = f"{query}"
                        limit = 1
            else:
                doi = search_dict.get("doi")
                if opasgenlib.not_empty(doi):
                    filter_q += f"&& art_doi:({doi}) "
                    limit = 1
                    
        if limit == 0: # not found special token
            art_id = search_dict.get("art_id")
            if opasgenlib.not_empty(art_id):
                limit = 1
                filter_q += f"&& art_id:({art_id}) "
            else:
                art_vol = search_dict.get("vol")
                if art_vol is not None:
                    if vol is None:
                        vol = art_vol.lstrip("0")
        
                art_pgrg = search_dict.get("pgrg")
                if opasgenlib.not_empty(art_pgrg):
                    # art_pgrg1 = art_pgrg.split("-")
                    if "-" in art_pgrg:
                        filter_q += f"&& art_pgrg:({art_pgrg}) "
                    else:
                        filter_q += f"&& art_pgrg:({art_pgrg}-*) "
        
                art_yr = search_dict.get("yr")
                if art_yr is not None:
                    if startyear is None and endyear is None:
                        startyear = art_yr
        
                art_authors = search_dict.get("author_list")
                if art_authors is not None:
                    if author is None:
                        author = art_authors
                
                art_author = search_dict.get("author")
                if art_author is not None:
                    if author is None:
                        author = f'"{art_author}"'
    
                title_search = search_dict.get("title")
                if title_search is not None:
                    if title is None:
                        title = title_search
                        
                word_search = search_dict.get("wordsearch")
                if word_search is not None:
                    if opasConfig.PARATEXT_SEARCH_METHOD == 1: # to turn on paragraph level 2 searches, but the simulation using proximity
                          # 25 words is what GVPi did and that matches better.
                        if paratext is None:
                            paratext = word_search
                    else:
                        art_level = 1
                        # if it already has a field name, it won't be a word search. so add body_xml as default
                        field_name = "body_xml"
                        if synonyms:
                            field_name += "_syn"
                        if 1:
                            search_q += f'&& {field_name}:({word_search}) '
                        else:
                            # is it in quotes?
                            m = re.match('([\"\'])(?P<q1>.*)([\"\'])', word_search)
                            if m:
                                q1 = m.group("q1")
                            else:
                                q1 = word_search
                                
                            if opasgenlib.not_empty(q1):
                                # unquoted string
                                m = re.search('\|{2,2}|\&{2,2}|\sand\s|\sor\s', q1, flags=re.IGNORECASE)
                                if m: # boolean, pass through
    
                                    search_q += f"&& {q1} "
                                else:
                                    # if it already has a field name, it won't be a word search. so add body_xml as default
                                    field_name = "body_xml"
                                    if synonyms:
                                        field_name += "_syn"
                                    if re.search("\"|\'", word_search):
                                        search_q += f'&& {field_name}:({word_search}) '
                                    else:
                                        search_q += f'&& {field_name}:"{word_search}"~25 '
                                       

    if art_level is not None:
        filter_q = f"&& art_level:{art_level} "  # for solr filter fq
        
    if solrQueryTermList is not None:
        # used for a queryTermList structure which is typically sent via the API endpoint body.
        # It allows each term to set some individual patterns, like turning on synonyms and the field add-on for synonyns
        # Right now, handles two levels...not sure yet how to do 3 if it ever comes to pass.
        # NOTE: default is now 1 for artLevel. Always specify it otherwise
        try:
                
            if solrQueryTermList.artLevel is None:
                artLevel = 1
            else:
                artLevel = solrQueryTermList.artLevel
                
            query_sub_clause = ""
            if artLevel == 2:
                # Set up child search prefix
                search_q_prefix = "{!parent which='art_level:1'} art_level:2 "
            else:
                search_q_prefix = ""
            
            # look for query clauses in body queryTermList       
            last_parent = None
            query = models.SolrQueryTerm()
            for query in solrQueryTermList.qt:
                boolean_connector = query.connector
                if artLevel == 2:
                    if query.parent is None:
                        solr_parent = schemaMap.user2solr("doc") # default
                    else:
                        solr_parent = schemaMap.user2solr(query.parent)
    
                    if last_parent is None:
                        last_parent = solr_parent
    
                    if last_parent != solr_parent:
                        boolean_connector = " || " # otherwise it will always rsult in empty set
                                                   #  because a paragraph can only be in parent
    
                if query.field is None:
                    if artLevel == 2:
                        use_field = "para"
                    else:
                        use_field = "text"
                else:
                    use_field = query.field
        
                if query.synonyms:
                    use_field = use_field + query.synonyms_suffix
                
                if opasgenlib.not_empty(query.words):
                    if use_field is not None:
                        sub_clause = f"{use_field}:({query.words})"
                    else:
                        sub_clause = f"({query.words})"

                    query_term_list.append(sub_clause)
                else:
                    sub_clause = ""
    
                if query_sub_clause != "":
                    query_sub_clause += " " + boolean_connector
                    
                if artLevel == 2 and solr_parent is not None:
                    query_sub_clause += f" (parent_tag:{solr_parent} AND {sub_clause}) "
                else:
                    query_sub_clause += f" {sub_clause}"
            
            if query_sub_clause != "":
                analyze_this = f"{search_q_prefix} && ({query_sub_clause})"
                search_q += analyze_this
                search_analysis_term_list.append(analyze_this)
    
            # now look for filter clauses in body queryTermList       
            filter_sub_clause = ""
            # qfilterTerm = ""
            filter_sub_clause = get_term_list_spec(solrQueryTermList.qf)
            if filter_sub_clause != "":
                analyze_this = f"&& ({filter_sub_clause})"
                filter_q += analyze_this
                search_analysis_term_list.append(analyze_this)
        except Exception as e:
            logger.error("Error setting up query term list from paratext (search)")
            
            
    if facetfields is not None:
        solr_query_spec.facetFields = opasgenlib.string_to_list(facetfields)
        solr_query_spec.facetMinCount=facetmincount
        solr_query_spec.facetSpec = facetspec
        if facetlimit is not None:
            solr_query_spec.facetSpec["facet_limit"] = facetlimit
        if facetoffset is not None:
            solr_query_spec.facetSpec["facet_offset"] = facetoffset
    
    if opasConfig.PARATEXT_SEARCH_METHOD == 1:
        if paratext is not None:
            # set up parameters as a solrQueryTermList to share that processing
            try:
                query_term_from_params = [
                                            models.SolrQueryTerm (
                                                                  connector="AND", 
                                                                  parent = parascope,
                                                                  field = "para",
                                                                  words = paratext,
                                                                  synonyms = synonyms,
                                                                  synonyms_suffix = opasConfig.SYNONYM_SUFFIX
                                                                )
                                         ]
        
                #  if a term list is supplied, add it to the list, otherwise, create list
                if solrQueryTermList is None:
                    solrQueryTermList = models.SolrQueryTermList(qt=query_term_from_params)
                    solrQueryTermList.artLevel = 2;
                else:
                    solrQueryTermList.qt.extend(query_term_from_params)
                    solrQueryTermList.artLevel = 2;
            except Exception as e:
                logger.error("Error setting up query term list from paratext (search)")
    else:
        if paratext is not None:
            # simulate paragraph search
            char_list = ["'", '"', "(", ")"]
            for c in paratext:
                if c in char_list:
                    para_search = False
                else:
                    para_search = True

            if para_search:
                para_parts = re.split("\s+OR|\|\|\s+", paratext)
                paratext_all = ""
                for n in para_parts:
                    if paratext_all != "":
                        paratext_all += " AND "
                    paratext_all += f'"{n}"~{opasConfig.PARA_MAX_WORD_DISTANCE}'
            else:
                paratext_all = paratext
                
            if fulltext1 is None:
                if parascope is None:
                    fulltext1 = paratext_all
                else:
                    parascope = parascope.replace("p_", "")
                    if parascope == "doc":
                        scope = "text_xml"
                    else:
                        scope = f"{parascope}_xml"
                        
                    fulltext1 = f"{scope}:({paratext_all})"
            #else, just use fulltext, ignore parascope:paratext

    if fulltext1 is not None:
        #  if there are no field specs in the fulltext spec
        if ":" not in fulltext1:
            fulltext1 = qparse.markup(fulltext1, "text")

        if synonyms:
            fulltext1 = fulltext1.replace("text:", "text_syn:")
            fulltext1 = fulltext1.replace("para:", "para_syn:")
            fulltext1 = fulltext1.replace("title:", "title_syn:")
            fulltext1 = fulltext1.replace("text_xml_offsite:", "text_xml_offsite_syn:")
            
        analyze_this = f"&& {fulltext1} "
        #if smart_to_fulltext1 is not None:
            #analyze_this += f"&& {smart_to_fulltext1} "
            
        if artLevel == 1:
            search_q += analyze_this
            filter_q += "&& art_level:1 "
        else: # we are looking at a child query, so put top level queries in the filter.
            filter_q += analyze_this
            
        search_analysis_term_list.append(analyze_this)
        query_term_list.append(fulltext1)
    
    if title is not None:
        title = title.strip()
        if title != '':
            title = qparse.markup(title, "title")
            if synonyms:
                title = title.replace("title:", "title_syn:")
            analyze_this = f"&& {title} "

            if artLevel == 1:
                search_q += analyze_this
            else: # we are looking at a child query, so put top level queries in the filter.
                filter_q += analyze_this

            search_analysis_term_list.append(analyze_this)  
            query_term_list.append(title)

    if opasgenlib.not_empty(source_name):
        # accepts a journal, book or video series name and optional wildcard.  No booleans.
        analyze_this = f"&& art_sourcetitlefull:({source_name}) "
        filter_q += analyze_this
        search_analysis_term_list.append(analyze_this)
        query_term_list.append(f"art_sourcetitlefull:({source_name})")       

    if opasgenlib.not_empty(source_type):  # source_type = book, journal, video ... (maybe more later)
        # accepts a source type or boolean combination of source types.
        source_type = qparse.markup(source_type, "art_sourcetype") # convert AND/OR/NOT, set up field
        analyze_this = f"&& {source_type} "
        filter_q += analyze_this
        search_analysis_term_list.append(analyze_this)  
        query_term_list.append(source_type)       

    if opasgenlib.not_empty(source_lang_code):  # source_language code, e.g., "EN" (added 2020-03, was omitted)
        # accepts a source language code list (e.g., EN, DE, ...).  If a list of codes with boolean connectors, changes to simple OR list
        source_lang_code = source_lang_code.lower()
        if "," in source_lang_code:
            source_lang_code = comma_sep_list_to_simple_bool(source_lang_code) #  in case it's comma separated list, in any case, convert to ||

        source_lang_code = qparse.markup(source_lang_code, "art_lang") # convert AND/OR/NOT, set up field
        analyze_this = f"&& {source_lang_code} "
        filter_q += analyze_this
        search_analysis_term_list.append(analyze_this)
        
    if opasgenlib.not_empty(source_code):
        # accepts a journal or book code (no wildcards) or a list of journal or book codes (no wildcards)
        # ALSO can accept a single source name or partial name with an optional wildcard.  But
        #   that's really what argument source_name is for, so this is just extra and may be later removed.
        code_for_query = ""
        analyze_this = ""
        # journal_code_list_pattern = "((?P<namelist>[A-z0-9]*[ ]*\+or\+[ ]*)+|(?P<namelist>[A-z0-9]))"
        journal_wildcard_pattern = r".*\*[ ]*"  # see if it ends in a * (wildcard)
        if re.match(journal_wildcard_pattern, source_code):
            # it's a wildcard pattern, it's a full source name
            code_for_query = source_code
            analyze_this = f"&& art_sourcetitlefull:({code_for_query}) "
            filter_q += analyze_this
        else:
            journal_code_list = source_code.upper().split(" OR ")
            if len(journal_code_list) > 1:
                journal_code_list = " OR ".join(journal_code_list)
                # convert to upper case
                code_for_query = f"art_sourcecode:({journal_code_list})"
                # it was a list.
                analyze_this = f"&& {code_for_query} "
                filter_q += analyze_this
            else:
                sourceInfo = sourceDB.lookupSourceCode(source_code.upper())
                if sourceInfo is not None or source_code.upper().strip('0123456789') == opasConfig.BOOKSOURCECODE:
                    # it's a single source code
                    code_for_query = source_code.upper()
                    analyze_this = f"&& art_sourcecode:({code_for_query}) "
                    filter_q += analyze_this
                else: # not a pattern, or a code, or a list of codes.
                    # must be a name
                    code_for_query = source_code
                    analyze_this = f"&& art_sourcetitlefull:({code_for_query}) "
                    filter_q += analyze_this

        search_analysis_term_list.append(analyze_this)
        # or it could be an abbreviation #TODO
        # or it counld be a complete name #TODO

    if opasgenlib.not_empty(cited_art_id):
        cited_art_id = cited_art_id.upper()
        cited = qparse.markup(cited_art_id, "bib_rx") # convert AND/OR/NOT, set up field query
        analyze_this = f"&& {cited} "
        filter_q += analyze_this
        search_analysis_term_list.append(analyze_this)  # Not collecting this!
    
    if opasgenlib.not_empty(vol):
        vol = qparse.markup(vol, "art_vol") # convert AND/OR/NOT, set up field query
        analyze_this = f"&& {vol} "
        filter_q += analyze_this
        search_analysis_term_list.append(analyze_this)  # Not collecting this!

    if opasgenlib.not_empty(issue):
        issue = qparse.markup(issue, "art_iss") # convert AND/OR/NOT, set up field query
        analyze_this = f"&& {issue} "
        filter_q += analyze_this
        search_analysis_term_list.append(analyze_this)  # Not collecting this!

    if opasgenlib.not_empty(author):
        author = author
        # if there's or and or not in lowercase, need to uppercase them
        # author = " ".join([x.upper() if x in ("or", "and", "not") else x for x in re.split("\s+(and|or|not)\s+", author)])
        # art_authors_citation:("tuckett, D.") OR art_authors_text:("tuckett, David")
        author_or_corrected = orclause_paren_wrapper(author)
            
        author_text = qparse.markup(author_or_corrected, "art_authors_text", quoted=False) # convert AND/OR/NOT, set up field query
        author_cited = qparse.markup(author_or_corrected, "art_authors_citation", quoted=False)
        analyze_this = f' && ({author_text} || {author_cited}) ' # search analysis
        filter_q += analyze_this        # query filter qf
        search_analysis_term_list.append(analyze_this)  
        query_term_list.append(author)       

    if opasgenlib.not_empty(articletype):
        # articletype = " ".join([x.upper() if x in ("or", "and", "not") else x for x in re.split("\s+(and|or|not)\s+", articletype)])
        articletype = qparse.markup(articletype, "art_type") # convert AND/OR/NOT, set up field query
        analyze_this = f"&& {articletype} "   # search analysis
        filter_q += analyze_this                         # query filter qf 
        search_analysis_term_list.append(analyze_this)
        query_term_list.append(articletype)       
        
    if opasgenlib.not_empty(datetype):
        #TODO for now, lets see if we need this. (We might not)
        pass

    if startyear is not None and endyear is None:
        # Only startyear specified, can use =. >, <, or - for range
        # parse startYear
        parsed_year_search = year_arg_parser(startyear)
        if parsed_year_search is not None:
            filter_q += parsed_year_search
            search_analysis_term_list.append(parsed_year_search)  
        else:
            logger.info(f"Search - StartYear bad argument {startyear}")

    if startyear is not None and endyear is not None:
        # put this in the filter query
        # should check to see if they are each dates
        if re.match("[12][0-9]{3,3}|\*", startyear) is None or re.match("[12][0-9]{3,3}|\*", endyear) is None:
            logger.info("Search - StartYear {} /Endyear {} bad arguments".format(startyear, endyear))
        else:
            analyze_this = f"&& art_year_int:[{startyear} TO {endyear}] "
            filter_q += analyze_this
            search_analysis_term_list.append(analyze_this)

    if startyear is None and endyear is not None:
        if re.match("[12][0-9]{3,3}", endyear) is None:
            logger.warning(f"Search - Endyear {endyear} bad argument")
        else:
            analyze_this = f"&& art_year_int:[* TO {endyear}] "
            filter_q += analyze_this
            search_analysis_term_list.append(analyze_this)

    if citecount is not None and citecount is not "0": #PEPSchemaSpecific
        # The PEP Solr database is set up so citation count fields map to 
        # 10, 20, and "all" year periods.
        # The citecount parameter can specify an integer count and a period:
        #  25 in 10                            (Solr/PEP schema mapping: art_cited_10:25)
        # or a range and a period:
        #  10 to 20 in 10                      (Solr/PEP schema mapping: art_cited_10:[10 TO 20])
        # or 
        #  10 to 20, 30 to 40 in 20            (Solr/PEP schema mapping: art_cited_20:([10 TO 20] OR [30 TO 40])
        #    which means either between 10 and 20, or between 30 and 40, in the last 20 years with data.
        #    'virtually' unlimited ranges can be specified.
        # or equivalently 
        #  10 to 20 OR 30 to 40 in 20            (Solr/PEP schema mapping: art_cited_20:([10 TO 20] OR [30 TO 40])
        # or 
        #  400 in ALL                          (Solr/PEP schema mapping: art_cited_all:25)
        #    which means 400 in all years with data. 
        # or
        #  10 to 20, 30 to * in 20            (Solr/PEP schema mapping: art_cited_20:([10 TO 20] OR [30 TO 40])
        #    which means 10 to 20 or 30 to the end of the range in 20 years
        # or
        #  * to 100 in 20            (Solr/PEP schema mapping: art_cited_20:([10 TO 20] OR [30 TO 40])
        #    which means from the start of range to 100 in 20 years
        # 
        # 'IN' is required along with a space in front of it and after it when specifying the period.
        # 
        # The default period is 5 years.

        val = None
        cited_in_period = None
        val_end = "*"
        match_ptn = "\s*(?P<nbr>[0-9]+)(\s+TO\s+(?P<endnbr>[0-9]+))?(\s+IN\s+(?P<period>(5|10|20|All)))?\s*"
        m = re.match(match_ptn, citecount, re.IGNORECASE)
        if m is not None:
            val = m.group("nbr")
            val_end = m.group("endnbr")
            if val_end is None:
                val_end = "*"
            cited_in_period = m.group("period")

        if val is None:
            val = 1
            
        if cited_in_period is None:
            cited_in_period = '5'

        range_list = opasgenlib.range_list(citecount)
        if range_list != "":
            analyze_this = f"&& art_cited_{cited_in_period.lower()}:({range_list})"
        else:
            analyze_this = f"&& art_cited_{cited_in_period.lower()}:[{val} TO {val_end}] "

        filter_q += analyze_this
        search_analysis_term_list.append(analyze_this)
        
    # if viewcount == 0, then it's not a criteria needed (same as None)
    # if user inputs text instead, also no criteria.
    if viewperiod is not None and viewcount is not None:
        val = None
        viewed_in_period = None
        val_end = "*"
        match_ptn = "\s*((?P<nbr>[0-9]+)(\s+TO\s+(?P<endnbr>[0-9]+))?\,?\s*)+(\s+IN\s+(?P<period>(lastweek|lastmonth|last6months|last12months|lastcalendaryear)))?\s*"
        m = re.match(match_ptn, viewcount, re.IGNORECASE)
        if m is not None:
            val = m.group("nbr")
            val_end = m.group("endnbr")
            if val_end is None:
                val_end = "*"
            viewed_in_period = m.group("period")
            
            # VALS_VIEWPERIODDICT_SOLRFIELDS = {1: "art_views_lastweek", 2: "art_views_last1mos", 3: "art_views_last6mos", 4: "art_views_last12mos", 5: "art_views_lastcalyear", 0: "art_views_lastcalyear" }  # not fond of zero, make both 5 and 0 lastcalyear
            if viewed_in_period == 'lastcalendaryear':
                view_count_field = opasConfig.VALS_VIEWPERIODDICT_SOLRFIELDS[5]
            elif viewed_in_period == 'last12months':
                view_count_field = opasConfig.VALS_VIEWPERIODDICT_SOLRFIELDS[4]
            elif viewed_in_period == 'last6months':
                view_count_field = opasConfig.VALS_VIEWPERIODDICT_SOLRFIELDS[3]
            elif viewed_in_period == 'lastmonth':
                view_count_field = opasConfig.VALS_VIEWPERIODDICT_SOLRFIELDS[2]
            elif viewed_in_period == 'lastweek':
                view_count_field = opasConfig.VALS_VIEWPERIODDICT_SOLRFIELDS[1]
            else:
                # use viewperiod, 0=last cal year, 1=last week, 2=last month, 3=last 6 months, 4=last 12 months (5=last cal year, just in case)
                # default=last12months
                view_count_field = opasConfig.VALS_VIEWPERIODDICT_SOLRFIELDS.get(viewperiod, "art_views_last12mos")
                
            range_list = opasgenlib.range_list(viewcount)
            if range_list != "":
                analyze_this = f"&& {view_count_field}:({range_list})"
            else:
                analyze_this = f"&& {view_count_field}:[{val} TO {val_end}] "
                
            filter_q += analyze_this
            search_analysis_term_list.append(analyze_this)
               
    # now clean up the final components.
    search_q = cleanup_solr_query(search_q)
    filter_q = cleanup_solr_query(filter_q)
    analyze_this = cleanup_solr_query(analyze_this)
    # get rid of extra spaces first, for consistency of matching.

    #if analyze_this is not None:
        ## no need to start with '&& '.  Remove it.
        #analyze_this = pat_prefix_amps.sub("", analyze_this)
    
    if search_analysis_term_list is not []:
        search_analysis_term_list = [cleanup_solr_query(x) for x in search_analysis_term_list]  

    if search_q == "*:*" and filter_q == "*:*":
        filter_q = "art_level:1"

    # Turn off highlighting if it's not needed, e.g, when there's no text search, e.g., a filter only, like mostcited and mostviewed calls
    # As of 2020-09-28, allow limit to be set here (via params)
    if highlightlimit is not None: # otherwise defaults to opasConfig.DEFAULT_MAX_KWIC_RETURNS (see SolrQueryOpts)
        if highlightlimit == 0: # max highlights to maark
            # solr wants a string boolean here (JSON style)
            solr_query_spec.solrQueryOpts.hl = "false"
        else:
            solr_query_spec.solrQueryOpts.hl = "true"
            solr_query_spec.solrQueryOpts.hlMaxKWICReturns = highlightlimit
            
    solr_query_spec.abstractReturn = abstract_requested
    solr_query_spec.returnFormat = format_requested # HTML, TEXT_ONLY, XML
    solr_query_spec.solrQuery.searchQ = search_q
    solr_query_spec.solrQuery.searchQPrefix = search_q_prefix
    solr_query_spec.solrQuery.filterQ = filter_q
    solr_query_spec.solrQuery.semanticDescription = search_result_explanation
    solr_query_spec.solrQuery.analyzeThis = analyze_this
    solr_query_spec.solrQuery.searchAnalysisTermList = search_analysis_term_list
    solr_query_spec.solrQuery.queryTermList = query_term_list
    solr_query_spec.solrQuery.sort = sort
    
    return solr_query_spec

# -------------------------------------------------------------------------------------------------------
def set_return_fields(solr_query_spec: models.SolrQuerySpec,
                      return_field_set=None,
                      return_field_options=None
                      ):

    if solr_query_spec is None:
        solr_query_spec = models.SolrQuerySpec() 
    
    if return_field_set is not None:
        solr_query_spec.returnFieldSet = return_field_set
    
    if solr_query_spec.returnFieldSet is not None:
        solr_query_spec.returnFieldSet = solr_query_spec.returnFieldSet.upper()
        
    if solr_query_spec.returnFieldSet == "DEFAULT":
        solr_query_spec.returnFields = opasConfig.DOCUMENT_ITEM_SUMMARY_FIELDS
    elif solr_query_spec.returnFieldSet == "TOC":
        solr_query_spec.returnFields = opasConfig.DOCUMENT_ITEM_TOC_FIELDS
    elif solr_query_spec.returnFieldSet == "META":
        solr_query_spec.returnFields = opasConfig.DOCUMENT_ITEM_META_FIELDS
    elif solr_query_spec.returnFieldSet == "FULL":
        solr_query_spec.returnFields = opasConfig.DOCUMENT_ITEM_SUMMARY_FIELDS
    elif solr_query_spec.returnFieldSet == "STAT":
        solr_query_spec.returnFields = opasConfig.DOCUMENT_ITEM_STAT_FIELDS
    elif solr_query_spec.returnFieldSet == "CONCORDANCE":
        solr_query_spec.returnFields = opasConfig.DOCUMENT_ITEM_CONCORDANCE_FIELDS
    else: #  true default!
        solr_query_spec.returnFieldSet = "DEFAULT"
        solr_query_spec.returnFields = opasConfig.DOCUMENT_ITEM_SUMMARY_FIELDS

    if return_field_options is not None:
        solr_query_spec.return_field_options = return_field_options 

    return solr_query_spec   
    
#================================================================================================================
def parse_to_query_spec(solr_query_spec: models.SolrQuerySpec = None,
                        core = None, 
                        req_url = None, 
                        query = None, 
                        filter_query = None,
                        query_debug = None,
                        similar_count = None,
                        full_text_requested = None,
                        abstract_requested = None, 
                        file_classification = None, 
                        format_requested = None,
                        return_field_set=None, 
                        def_type = None,
                        summary_fields = None, 
                        highlight_fields = None,
                        facet_fields = None,
                        facet_mincount = None, 
                        extra_context_len = None,
                        highlightlimit = None,
                        sort= None,
                        limit = None, 
                        offset = None,
                        page_offset = None,
                        page_limit = None,
                        page = None, 
                        option_flags=0
                        ):
    """
    This function creates or updates a SolrQuerySpec, with the caller specifying the Solr query and filter query fields
    and other options directly.

    The caller sends the Query using the models.SolrQuerySpec, with the option of including other parameters to override
    the values in models.SolrQuerySpec.
    
    """
    if solr_query_spec is None:
        #  create it
        
        solr_query_spec = models.SolrQuerySpec(
                                               solrQuery=models.SolrQuery(), 
                                               solrQueryOpts=models.SolrQueryOpts()
        )
        
    if solr_query_spec.solrQuery is None:
        solr_query_spec.solrQuery = models.SolrQuery() 
    
    if solr_query_spec.solrQueryOpts is None:
        solr_query_spec.solrQueryOpts = models.SolrQueryOpts() 
    
    # Use SET to offer predefined set of returned fields, so we know what can come back.
    # Note that the larger fields, e.g., abstract, document, are added later based on other attributes
    # Need to check what fields they asked for, and make sure no document fields were specified!
    
    solr_query_spec = set_return_fields(solr_query_spec, return_field_set=return_field_set)
    
    #Always add id and file_classification to return fields
    solr_query_spec.returnFields += ", id, file_classification" #  need to always return id

    if full_text_requested is not None:
        solr_query_spec.fullReturn = full_text_requested

    if abstract_requested is not None:
        solr_query_spec.abstractReturn = abstract_requested 

    # don't let them specify text fields to bring back full-text content in at least PEP schema fields in 
    #   docs or glossary.
    # however, we add it if they are authenticated, and then check by document.
    # Should we take away para?
    #  try to reduce amount of data coming back based on needs...
    #  Set it to use the main structure returnFields; eventually delete the one in the query sub
    #if solr_query_spec.abstractReturn:
        #if "abstract_xml" not in solr_query_spec.returnFields:
            #solr_query_spec.returnFields += ", abstract_xml"
        #if "art_excerpt" not in solr_query_spec.returnFields:
            #solr_query_spec.returnFields += ", art_excerpt, art_excerpt_xml"
        #if "summaries_xml" not in solr_query_spec.returnFields:
            #solr_query_spec.returnFields += ", summaries_xml"
    #elif solr_query_spec.fullReturn: #and session_info.XXXauthenticated:
        ## NOTE: we add this here, but in return data, access by document will be checked.
        #if "text_xml" not in solr_query_spec.returnFields:
            #solr_query_spec.returnFields += ", text_xml, art_excerpt, art_excerpt_xml, para"
    #else: # remove fulltext fields
        #solr_query_spec.returnFields = re.sub("(,\s*?)?[^A-z0-9](text_xml|para|term_def_rest_xml)[^A-z0-9]", "", solr_query_spec.returnFields)


    # parameters specified override QuerySpec
    
    if file_classification is not None:
        solr_query_spec.fileClassification = file_classification 

    if query_debug is not None:
        solr_query_spec.solrQueryOpts.queryDebug = query_debug 

    if solr_query_spec.solrQueryOpts.queryDebug != "on":
        solr_query_spec.solrQueryOpts.queryDebug = "off"

    if req_url is not None:
        solr_query_spec.urlRequest = req_url

    if format_requested is not None:
        solr_query_spec.returnFormat = format_requested

    if option_flags is not None:
        # See opasConfig
        #OPTION_NO_GLOSSARY_MARKUP = 1
        #OPTION_2_RESERVED = 2
        #OPTION_3_RESERVED = 4
        #OPTION_4_RESERVED = 8
        #OPTION_5_RESERVED = 16
        solr_query_spec.returnOptions = {}
        if option_flags & opasConfig.OPTION_1_NO_GLOSSARY_TERM_MARKUP:
            # glossary Term markup off
            solr_query_spec.returnOptions["Glossary"] = False
 
    if limit is not None:
        solr_query_spec.limit = limit

    if offset is not None:
        solr_query_spec.offset = offset

    if page_offset is not None:
        solr_query_spec.page_offset = page_offset

    if page_limit is not None:
        solr_query_spec.page_limit = page_limit

    if page is not None:
        solr_query_spec.page = page

    # part of the query model

    if opasgenlib.not_empty(query):
        solr_query_spec.solrQuery.searchQ = query
        logger.debug(f"query: {query}. Request: {req_url}")
    else:
        if is_empty(solr_query_spec.solrQuery.searchQ):
            logger.debug(f"query and searchQ were None or empty. Chgd to *:*. {query}. Request: {req_url}")
            solr_query_spec.solrQuery.searchQ = "*:*"       

    if filter_query is not None:
        solr_query_spec.solrQuery.filterQ = filter_query

    if opasgenlib.not_empty(solr_query_spec.solrQuery.filterQ):
        # for logging/debug
        solr_query_spec.solrQuery.filterQ = solr_query_spec.solrQuery.filterQ.replace("*:* && ", "")
        logger.debug("Solr FilterQ: %s", filter_query)
    else:
        solr_query_spec.solrQuery.filterQ = "*:*"
        
    #  clean up spaces and cr's from in code readable formatting
    if opasgenlib.not_empty(solr_query_spec.returnFields):
        solr_query_spec.returnFields = ", ".join(e.lstrip() for e in solr_query_spec.returnFields.split(","))

    if sort is not None:
        if " asc" not in sort and " desc" not in sort:
            sort = sort + " asc"
            
        solr_query_spec.solrQuery.sort = sort

    #  part of the options model

    if similar_count is not None:
        solr_query_spec.solrQueryOpts.moreLikeThisCount = similar_count
        
    if def_type is not None:
        solr_query_spec.solrQueryOpts.defType = def_type 

    if highlight_fields is not None:
        solr_query_spec.solrQueryOpts.hlFields = highlight_fields 

    if facet_fields is not None:
        if type(facet_fields) == list:
            solr_query_spec.facetFields = facet_fields
        else:
            solr_query_spec.facetFields = opasgenlib.string_to_list(facet_fields)
    else:
        solr_query_spec.facetFields = opasgenlib.string_to_list(solr_query_spec.facetFields)
        
    if facet_mincount is not None:
        solr_query_spec.facetMinCount = facet_mincount
        
    if extra_context_len is not None:
        solr_query_spec.solrQueryOpts.hlFragsize = max(extra_context_len, opasConfig.DEFAULT_KWIC_CONTENT_LENGTH)
    else:
        try:
            solr_query_spec.solrQueryOpts.hlFragsize = max(solr_query_spec.solrQueryOpts.hlFragsize, opasConfig.DEFAULT_KWIC_CONTENT_LENGTH)
        except:
            solr_query_spec.solrQueryOpts.hlFragsize = opasConfig.DEFAULT_KWIC_CONTENT_LENGTH

    # taken care of later in search_text_qs        
    #if solr_query_spec.solrQueryOpts.hlMaxAnalyzedChars is 0 or solr_query_spec.solrQueryOpts.hlMaxAnalyzedChars is None:
        #solr_query_spec.solrQueryOpts.hlMaxAnalyzedChars = solr_query_spec.solrQueryOpts.hlFragsize  
        
    if highlightlimit is not None:
        solr_query_spec.solrQueryOpts.hlSnippets = highlightlimit # highlighting_max_snips 
       
    ret_val = solr_query_spec
    
    if ret_val is None:
        logger.error("Parse to query spec should never return none.")
    
    return ret_val

#-----------------------------------------------------------------------------
def get_parent_data(child_para_id, documentListItem=None):
    """
    Returns True if the value is found in the field specified in the docs core.
    
    """
    m = re.match(".*\..*\.*(^\..*)", child_para_id)
    if m is not None:
        parent_id = m.group(0)
        if parent_id is not None:
            try:
                q_str = f"art_level:1 && art_id:{art_id}"
                logger.info(f"Solr Query: q={q_str}")
                results = solr_docs.query(q = q_str,  
                                          fields = f"art_year, id, art_citeas_xml, file_classification, art_isbn, art_issn, art_pgrg", 
                                          rows = 1,
                                          )
            except Exception as e:
                logger.warning(f"Solr query: {q} fields {field} {e}")
           
    if len(results) > 0:
        result = results.results[0]
        if documentListItem is None:
            ret_val = models.DocumentListItem(**result)
        else:
            ret_val = documentListItem
            
        ret_val = get_base_article_info_from_search_result(result, ret_val)
    else:
        if documentListItem is None:
            ret_val = models.DocumentListItem()
        else:
            ret_val = documentListItem

    return ret_val

#-----------------------------------------------------------------------------
def get_excerpt_from_search_result(result, documentListItem: models.DocumentListItem, ret_format="HTML", omit_abstract=False):
    """
    pass in the result from a solr query and this retrieves the abstract/excerpt from the excerpt field
     which is stored based on the abstract or summary or the first page of the document.

     Substituted for dynamic generation of excerpt 2020-02-26
    """
    # make sure basic info has been retrieved
    if documentListItem.sourceTitle is None:
        documentListItem = get_base_article_info_from_search_result(result, documentListItem)

    try:
        art_excerpt = result["art_excerpt"]
    except KeyError as e:
        art_excerpt  = "No abstract found for this title, or no abstract requested in search options."
        logger.info("No excerpt for document ID: %s", documentListItem.documentID)

    # experimental - remove abstract if not authenticated
    if art_excerpt == "[]" or art_excerpt is None:
        abstract = None
    else:
        if omit_abstract:
            art_excerpt = opasConfig.ACCESS_ABSTRACT_RESTRICTED_MESSAGE
        
        heading = opasxmllib.get_running_head(source_title=documentListItem.sourceTitle,
                                              pub_year=documentListItem.year,
                                              vol=documentListItem.vol,
                                              issue=documentListItem.issue,
                                              pgrg=documentListItem.pgRg,
                                              ret_format=ret_format)

        if not omit_abstract:
            art_excerpt = result.get("art_excerpt_xml", art_excerpt)
        else:
            art_excerpt = f"<abs><p>{art_excerpt}</p></abs>"
            
        abs_xml = f"""<pepkbd3>{documentListItem.documentInfoXML}{art_excerpt}<body/></pepkbd3>"""

        try:
            ret_format = ret_format.upper()
        except Exception as e:
            logger.warning(f"Invalid return format: {ret_format}.  Using default. Error {e}.")
            ret_format = "HTML"

        if ret_format == "TEXTONLY":
            art_excerpt = opasxmllib.xml_elem_or_str_to_text(art_excerpt)
            abstract = f"""
                        {heading}\n{documentListItem.title}\n{documentListItem.authorMast}\n\n
                        {art_excerpt}
                        """
        elif ret_format == "XML":
            # for now, this is only an xml fragment so it's not quite as DTD specific.
            abstract = abs_xml
            
        else: # ret_format == "HTML":
            abstract = opasxmllib.xml_str_to_html(abs_xml)

    # return it in the abstract field for display
    documentListItem.abstract = abstract

    return documentListItem

#-----------------------------------------------------------------------------
def get_base_article_info_from_search_result(result, documentListItem: models.DocumentListItem):
    
    if result is not None:
        documentListItem.documentID = result.get("art_id", None)
        documentListItem.docLevel = result.get("art_level", None)
        documentListItem.PEPCode = result.get("art_sourcecode", None)
        parent_tag = result.get("parent_tag", None)

        if result.get("meta_xml", None): documentListItem.documentMetaXML = result.get("meta_xml", None)
        if result.get("art_info_xml", None): documentListItem.documentInfoXML = result.get("art_info_xml", None)
        if result.get("art_pgrg", None): documentListItem.pgRg = result.get("art_pgrg", None)
        art_lang = result.get("art_lang", None)
        if isinstance(art_lang, list):
            art_lang = art_lang[0]
        documentListItem.lang=art_lang
        documentListItem.year = result.get("art_year", None)
        documentListItem.vol = result.get("art_vol", None)
        documentListItem.docType = result.get("art_type", None)
        if result.get("art_doi", None): documentListItem.doi = result.get("art_doi", None)
        documentListItem.issue = result.get("art_iss", None)
        documentListItem.issn = result.get("art_issn", None)
        # documentListItem.isbn = result.get("art_isbn", None) # no isbn in solr stored data, only in products table
        # see if using art_title instead is a problem for clients...at least that drops the footnote
        documentListItem.title = result.get("art_title", "")  
        # documentListItem.title = result.get("art_title_xml", "")  
        if documentListItem.pgRg is not None:
            pg_start, pg_end = opasgenlib.pgrg_splitter(documentListItem.pgRg)
            documentListItem.pgStart = pg_start
            documentListItem.pgEnd = pg_end

        if result.get("art_origrx", None): documentListItem.origrx = result.get("art_origrx", None)
        if result.get("art_qual", None): documentListItem.relatedrx= result.get("art_qual", None)
        documentListItem.sourceTitle = result.get("art_sourcetitlefull", None)
        documentListItem.sourceType = result.get("art_sourcetype", None)
        author_ids = result.get("art_authors", None)
        if author_ids is None:
            # try this, instead of abberrant behavior in alpha of display None!
            documentListItem.authorMast = result.get("art_authors_mast", "")
        else:
            documentListItem.authorMast = opasgenlib.derive_author_mast(author_ids)
        if result.get("art_newsecnm", None): documentListItem.newSectionName=result.get("art_newsecnm", None)            
        citeas = result.get("art_citeas_xml", None)
        citeas = force_string_return_from_various_return_types(citeas)
        documentListItem.documentRef = opasxmllib.xml_elem_or_str_to_text(citeas, default_return="")
        documentListItem.documentRefHTML = citeas
        documentListItem.updated=result.get("file_last_modified", None)
        documentListItem.accessClassification = result.get("file_classification", opasConfig.DOCUMENT_ACCESS_ARCHIVE)

        if parent_tag is not None:
            documentListItem.docChild = {}
            documentListItem.docChild["id"] = result.get("id", None)
            documentListItem.docChild["parent_tag"] = parent_tag
            documentListItem.docChild["para"] = result.get("para", None)
            documentListItem.docChild["lang"] = result.get("lang", None)
            if isinstance(documentListItem.docChild["lang"], list):
                documentListItem.docChild["lang"] = documentListItem.docChild["lang"][0]
            documentListItem.docChild["para_art_id"] = result.get("para_art_id", None)
        
        para_art_id = result.get("para_art_id", None)
        if documentListItem.documentID is None and para_art_id is not None:
            # this is part of a document, we should retrieve the parent info
            top_level_doc = get_base_article_info_by_id(art_id=para_art_id)
            if top_level_doc is not None:
                documentListItem = merge_documentListItems(documentListItem, top_level_doc)

        # don't set the value, if it's None, so it's not included at all in the pydantic return
        # temp workaround for art_lang change

    return documentListItem # return a partially filled document list item

#def get_fulltext_new(documentListItem, solr_query_spec):
    ## consolidated full-text handling.
    
    #child_xml = None
    #offset = 0
    ##if documentListItem.sourceTitle is None:
        ##documentListItem = get_base_article_info_from_search_result(result, documentListItem)
        
    ##if page_limit is None:
        ##page_limit = opasConfig.DEFAULT_PAGE_LIMIT

    #format_requested=solr_query_spec.returnFormat,
    #return_options=solr_query_spec.returnOptions, 
    #documentListItem.docPagingInfo = {}    
    #documentListItem.docPagingInfo["page"] = solr_query_spec.page,
    #documentListItem.docPagingInfo["page_limit"] = solr_query_spec.page_limit
    #documentListItem.docPagingInfo["page_offset"] = page_offset=solr_query_spec.page_offset

    #fullText = documentListItem.document # result.get("text_xml", None)
    #text_xml = force_string_return_from_various_return_types(fullText)
    #if fullText is not None:
        #if len(fullText) > len(text_xml):
            #logger.warning("Warning: text with highlighting is smaller than full-text area.  Returning without hit highlighting.")
            #text_xml = fullText

    #if text_xml is not None:
        #reduce = False
        ## see if an excerpt was requested.
        #if page is not None and page <= int(documentListItem.pgEnd) and page > int(documentListItem.pgStart):
            ## use page to grab the starting page
            ## we've already done the search, so set page offset and limit these so they are returned as offset and limit per V1 API
            #offset = page - int(documentListItem.pgStart)
            #reduce = True
        ## Only use supplied offset if page parameter is out of range, or not supplied
        #if reduce == False and page_offset is not None and page_offset != 0: 
            #offset = page_offset
            #reduce = True

        #if reduce == True or page_limit is not None:
            ## extract the requested pages
            #try:
                #temp_xml = opasxmllib.xml_get_pages(xmlstr=text_xml,
                                                    #offset=offset,
                                                    #limit=page_limit,
                                                    #pagebrk="pb",
                                                    #inside="body",
                                                    #env="body")
                #temp_xml = temp_xml[0]
                
            #except Exception as e:
                #logger.error(f"Page extraction from document failed. Error: {e}.  Keeping entire document.")
            #else: # ok
                #text_xml = temp_xml
    
        #if return_options is not None:
            #if return_options.get("Glossary", None) == False:
                ## remove glossary markup
                #text_xml = opasxmllib.remove_glossary_impx(text_xml)   
    
    #try:
        #format_requested_ci = format_requested.lower() # just in case someone passes in a wrong type
    #except:
        #format_requested_ci = "html"

    #if documentListItem.docChild != {} and documentListItem.docChild is not None:
        #child_xml = documentListItem.docChild["para"]
    #else:
        #child_xml = None
    
    #if text_xml is None and child_xml is not None:
        #text_xml = child_xml

    ## ####################################
    ## here's where we need to massage hit markup
    ## ####################################
    ## TBD

    #if format_requested_ci == "html":
        ## Convert to HTML
        #heading = opasxmllib.get_running_head( source_title=documentListItem.sourceTitle,
                                               #pub_year=documentListItem.year,
                                               #vol=documentListItem.vol,
                                               #issue=documentListItem.issue,
                                               #pgrg=documentListItem.pgRg,
                                               #ret_format="HTML"
                                               #)
        #try:
            #text_xml = opasxmllib.xml_str_to_html(text_xml)  #  e.g, r"./libs/styles/pepkbd3-html.xslt"
        #except Exception as e:
            #logger.error(f"Could not convert to HTML {e}; returning native format")
            #text_xml = re.sub(f"{opasConfig.HITMARKERSTART}|{opasConfig.HITMARKEREND}", numbered_anchors, text_xml)
        #else:
            #try:
                #global count_anchors
                #count_anchors = 0
                ## print (f"Hitmarkers: {opasConfig.HITMARKERSTART}, {opasConfig.HITMARKEREND}, Count_Anchors: {count_anchors}")
                #text_xml = re.sub(f"{opasConfig.HITMARKERSTART}|{opasConfig.HITMARKEREND}", numbered_anchors, text_xml)
                #text_xml = re.sub("\[\[RunningHead\]\]", f"{heading}", text_xml, count=1)
            #except Exception as e:
                #logger.error(f"Could not do substitution {e}")

        #if child_xml is not None:
            #child_xml = opasxmllib.xml_str_to_html(child_xml)
                
    #elif format_requested_ci == "textonly":
        ## strip tags
        #text_xml = opasxmllib.xml_elem_or_str_to_text(text_xml, default_return=text_xml)
        #if child_xml is not None:
            #child_xml = opasxmllib.xml_elem_or_str_to_text(child_xml, default_return=text_xml)
    #elif format_requested_ci == "xml":
        ## don't do this for XML
        #pass
        ## text_xml = re.sub(f"{opasConfig.HITMARKERSTART}|{opasConfig.HITMARKEREND}", numbered_anchors, text_xml)
        ## child_xml = child_xml

    #documentListItem.document = text_xml
                
    #if child_xml is not None:
        ## return child para in requested format
        #documentListItem.docChild['para'] = child_xml

    #if documentListItem.document == None:
        #errmsg = f"Document fetch failed! ({solr_query_spec.solrQuery.searchQ}"
        #logger.error(errmsg)
        #documentListItem.term = f"SearchHits({solr_query_spec.solrQuery.searchQ})"
        #documentListItem.termCount = 0
    #else:
        #try:
            #matches = re.findall(f"class='searchhit'|{opasConfig.HITMARKERSTART}", documentListItem.document)
        #except Exception as e:
            #logger.warning(f"Exception.  Could not count matches. {e}")
            #documentListItem.term = f"SearchHits({solr_query_spec.solrQuery.searchQ})"
            #documentListItem.termCount = 0
        #else:
            #documentListItem.term = f"SearchHits({solr_query_spec.solrQuery.searchQ})"
            #documentListItem.termCount = len(matches)

    #return documentListItem

    
##-----------------------------------------------------------------------------
#def get_fulltext_from_search_results(result,
                                     #text_xml,
                                     #page,
                                     #page_offset,
                                     #page_limit,
                                     #documentListItem: models.DocumentListItem,
                                     #format_requested="HTML",
                                     #return_options=None):

    #child_xml = None
    #offset = 0
    #if documentListItem.sourceTitle is None:
        #documentListItem = get_base_article_info_from_search_result(result, documentListItem)
        
    ##if page_limit is None:
        ##page_limit = opasConfig.DEFAULT_PAGE_LIMIT

    #documentListItem.docPagingInfo = {}    
    #documentListItem.docPagingInfo["page"] = page
    #documentListItem.docPagingInfo["page_limit"] = page_limit
    #documentListItem.docPagingInfo["page_offset"] = page_offset

    #fullText = result.get("text_xml", None)
    #text_xml = force_string_return_from_various_return_types(text_xml)
    #if text_xml is None:  # no highlights, so get it from the main area
        #try:
            #text_xml = fullText
        #except:
            #text_xml = None

    #elif fullText is not None:
        #if len(fullText) > len(text_xml):
            #logger.warning("Warning: text with highlighting is smaller than full-text area.  Returning without hit highlighting.")
            #text_xml = fullText

    #if text_xml is not None:
        #reduce = False
        ## see if an excerpt was requested.
        #if page is not None and page <= int(documentListItem.pgEnd) and page > int(documentListItem.pgStart):
            ## use page to grab the starting page
            ## we've already done the search, so set page offset and limit these so they are returned as offset and limit per V1 API
            #offset = page - int(documentListItem.pgStart)
            #reduce = True
        ## Only use supplied offset if page parameter is out of range, or not supplied
        #if reduce == False and page_offset is not None and page_offset != 0: 
            #offset = page_offset
            #reduce = True

        #if reduce == True or page_limit is not None:
            ## extract the requested pages
            #try:
                #temp_xml = opasxmllib.xml_get_pages(xmlstr=text_xml,
                                                    #offset=offset,
                                                    #limit=page_limit,
                                                    #pagebrk="pb",
                                                    #inside="body",
                                                    #env="body")
                #temp_xml = temp_xml[0]
                
            #except Exception as e:
                #logger.error(f"Page extraction from document failed. Error: {e}.  Keeping entire document.")
            #else: # ok
                #text_xml = temp_xml
    
        #if return_options is not None:
            #if return_options.get("Glossary", None) == False:
                ## remove glossary markup
                #text_xml = opasxmllib.remove_glossary_impx(text_xml)   
    
    #try:
        #format_requested_ci = format_requested.lower() # just in case someone passes in a wrong type
    #except:
        #format_requested_ci = "html"

    #if documentListItem.docChild != {} and documentListItem.docChild is not None:
        #child_xml = documentListItem.docChild["para"]
    #else:
        #child_xml = None
    
    #if text_xml is None and child_xml is not None:
        #text_xml = child_xml
        
    #try:
        ##ret_val.documents.responseSet[0].hitCriteria = urllib.parse.unquote(search) 
        ## remove nuisance stop words from matches
        #text_xml = opasAPISupportLib.remove_nuisance_word_hits(text_xml)
    #except Exception as e:
        #print (f"Error removing nuisance hits: {e}")

    #if format_requested_ci == "html":
        ## Convert to HTML
        #heading = opasxmllib.get_running_head( source_title=documentListItem.sourceTitle,
                                               #pub_year=documentListItem.year,
                                               #vol=documentListItem.vol,
                                               #issue=documentListItem.issue,
                                               #pgrg=documentListItem.pgRg,
                                               #ret_format="HTML"
                                               #)
        #try:
            #text_xml = opasxmllib.xml_str_to_html(text_xml)  #  e.g, r"./libs/styles/pepkbd3-html.xslt"
        #except Exception as e:
            #logger.error(f"Could not convert to HTML {e}; returning native format")
            #text_xml = re.sub(f"{opasConfig.HITMARKERSTART}|{opasConfig.HITMARKEREND}", numbered_anchors, text_xml)
        #else:
            #try:
                #global count_anchors
                #count_anchors = 0
                ## print (f"Hitmarkers: {opasConfig.HITMARKERSTART}, {opasConfig.HITMARKEREND}, Count_Anchors: {count_anchors}")
                #text_xml = re.sub(f"{opasConfig.HITMARKERSTART}|{opasConfig.HITMARKEREND}", numbered_anchors, text_xml)
                #text_xml = re.sub("\[\[RunningHead\]\]", f"{heading}", text_xml, count=1)
            #except Exception as e:
                #logger.error(f"Could not do substitution {e}")

        #if child_xml is not None:
            #child_xml = opasxmllib.xml_str_to_html(child_xml)
                
    #elif format_requested_ci == "textonly":
        ## strip tags
        #text_xml = opasxmllib.xml_elem_or_str_to_text(text_xml, default_return=text_xml)
        #if child_xml is not None:
            #child_xml = opasxmllib.xml_elem_or_str_to_text(child_xml, default_return=text_xml)
    #elif format_requested_ci == "xml":
        ## don't do this for XML
        #pass
        ## text_xml = re.sub(f"{opasConfig.HITMARKERSTART}|{opasConfig.HITMARKEREND}", numbered_anchors, text_xml)
        ## child_xml = child_xml

    #documentListItem.document = text_xml
                
    #if child_xml is not None:
        ## return child para in requested format
        #documentListItem.docChild['para'] = child_xml

    #return documentListItem

#-----------------------------------------------------------------------------
def merge_documentListItems(old, new):     
    if old.documentID is None: old.documentID = new.documentID
    if old.PEPCode is None: old.PEPCode = new.PEPCode
    if old.documentMetaXML is None: old.documentMetaXML = new.documentMetaXML
    if old.documentInfoXML is None: old.documentInfoXML = new.documentInfoXML
    if old.pgRg is None: old.pgRg = new.pgRg
    if old.lang  is None: old.lang  = new.lang
    if old.origrx is None: old.origrx = new.origrx   
    if old.relatedrx is None: old.relatedrx = new.relatedrx 
    if old.sourceTitle is None: old.sourceTitle = new.sourceTitle 
    if old.sourceType is None: old.sourceType = new.sourceType 
    if old.year is None: old.year = new.year  
    if old.vol is None: old.vol = new.vol  
    if old.docType is None: old.docType = new.docType 
    if old.doi is None: old.doi = new.doi
    if old.issue is None: old.issue = new.issue 
    if old.issn is None: old.issn = new.issn 
    if old.title is None: old.title = new.title 
    if old.pgRg is None: old.pgRg = new.pgRg 
    if old.authorMast is None: old.authorMast = new.authorMast 
    if old.newSectionName is None: old.newSectionName = new.newSectionName 
    if old.documentRef is None: old.documentRef = new.documentRef  
    if old.documentRefHTML is None: old.documentRefHTML = new.documentRefHTML  
    if old.updated is None: old.updated = new.updated 
    if old.accessClassification is None: old.accessClassification = new.accessClassification 
    if old.accessLimited is None: old.accessLimited = new.accessLimited
    if old.accessLimitedCurrentContent is None: old.accessLimitedCurrentContent = new.accessLimitedCurrentContent
    if old.accessLimitedDescription is None: old.accessLimitedDescription = new.accessLimitedDescription 
    if old.accessLimitedPubLink is None: old.accessLimitedPubLink = new.accessLimitedPubLink 
    if old.accessLimitedReason is None: old.accessLimitedReason = new.accessLimitedReason

    return old

#-----------------------------------------------------------------------------
def quick_docmeta_docsearch(q_str,
                            fields=None,
                            req_url=None, 
                            limit=10,
                            offset=0):
    ret_val = None
    count = 0
    if fields is None:
        fields = opasConfig.DOCUMENT_ITEM_SUMMARY_FIELDS
        
    logger.info(f"Solr Query: q={q_str}")
    results = solr_docs.query(q = q_str, fields = fields, limit=limit, offset=offset)
    document_item_list = []
    count = len(results)
    try:
        for result in results:
            documentListItem = models.DocumentListItem()
            documentListItem = get_base_article_info_from_search_result(result, documentListItem)
            document_item_list.append(documentListItem)
    except IndexError as e:
        logger.warning("No matching entry for %s.  Error: %s", (q_str, e))
    except KeyError as e:
        logger.warning("No content found for %s.  Error: %s", (q_str, e))
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

    return ret_val, count
    
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
            if text_str == []:
                ret_val = None
            else:
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

# -------------------------------------------------------------------------------------------------------
# run it!

if __name__ == "__main__":
    import sys
    print ("Running in Python %s" % sys.version_info[0])

    ret = check_search_args(
        smarttext="abcdefg",
        fulltext1='body_xml:("Evenly Suspended Attention"~25) && body_xml:(tuckett)',
        paratext="hij", author="klm", title="nop", startyear="1922", endyear="2020"
    )
    
    print (ret)
    
    import doctest
    doctest.testmod()
    print ("Fini. OpasQueryHelper Tests complete.")
    sys.exit()
    
    # this was a test for QueryTextToSolr class, the parser part, but not using that now.
    #tests = ["see dick run 'run dick run' ",
             #"road car truck semi or 'driving too fast'",
             #"or and not", 
             #"dog or 'fred flints*' and 'barney rubble'",
             #"dog and cat and ^provided", 
             #"dog and (cat or flea)",
             #"dog and ^(cat or flea)",
             #"dog or 'fred flintstone' and ^'barney rubble'",
             #"fr* and flintstone or ^barney",
             #"dog and (cat and flea)",
             #"dog or cat",
             #"fleet footed", 
             #"dog and ^cat or ^mouse and pig or hawk", 
             #"dog AND cat or 'mouse pig'", 
             #"dog AND cat or ^'mouse pig bird'",
             #"'freudian slip' or 'exposure therapy'"
             #]
    
    #label_word = "text_xml"
    #for n in tests:
        #mu = QueryTextToSolr()
        #print (n, ":", mu.markup(n, label_word))
    
