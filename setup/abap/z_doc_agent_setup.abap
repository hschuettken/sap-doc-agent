*&---------------------------------------------------------------------*
*& Report Z_DOC_AGENT_SETUP
*&---------------------------------------------------------------------*
*& Purpose: Configure the sap-doc-agent transport backend and store
*&          settings in ZDOC_AGENT_CFG. Run this once before the
*&          first scan.
*&
*& NOTE: The three database tables must be created in SE11 before
*&       running this program. DDL documentation is included below.
*&
*& Tables required (create manually in SE11 before running):
*&
*&  ZDOC_AGENT_CFG
*&    MANDT    CLNT 3         Client (key)
*&    CFG_KEY  CHAR 30        Config key (key)
*&    CFG_VALUE CHAR 255      Config value
*&
*&  ZDOC_AGENT_SCAN
*&    MANDT       CLNT 3      Client (key)
*&    OBJECT_KEY  CHAR 60     Unique object identifier (key)
*&    OBJECT_TYPE CHAR 20     Object type (ADSO, CLASS, FM, ...)
*&    DESCRIPTION CHAR 255    Human-readable description
*&    PACKAGE     CHAR 30     ABAP package (DEVCLASS)
*&    OWNER       CHAR 12     Last changed by (AENAM)
*&    LAST_SCAN   DEC  15     Scan timestamp (TIMESTAMP format)
*&    CONTENT_HASH CHAR 64    SHA-256 hex of source/metadata
*&    SOURCE_CODE STRG        Extracted ABAP source code
*&    METADATA    STRG        JSON metadata (depends on object type)
*&
*&  ZDOC_AGENT_DEPS
*&    MANDT      CLNT 3       Client (key)
*&    SOURCE_KEY CHAR 60      Source object key (key)
*&    TARGET_KEY CHAR 60      Target object key (key)
*&    DEP_TYPE   CHAR 20      Dependency type (key)
*&                            e.g. USES_FM, INCLUDES, READS_TABLE,
*&                                 CALLS_CLASS, CHAIN_STEP
*&
*&---------------------------------------------------------------------*
REPORT z_doc_agent_setup.

*----------------------------------------------------------------------*
* Type definitions
*----------------------------------------------------------------------*
TYPES:
  BEGIN OF ty_cfg_entry,
    mandt     TYPE mandt,
    cfg_key   TYPE c LENGTH 30,
    cfg_value TYPE c LENGTH 255,
  END OF ty_cfg_entry.

*----------------------------------------------------------------------*
* Selection screen
*----------------------------------------------------------------------*
SELECTION-SCREEN BEGIN OF BLOCK transport WITH FRAME TITLE TEXT-001.
  PARAMETERS:
    p_trans   TYPE c LENGTH 1 DEFAULT 'P'
              OBLIGATORY,
    p_giturl  TYPE c LENGTH 255,
    p_token   TYPE c LENGTH 255,
    p_nsfiltr TYPE c LENGTH 30  DEFAULT 'Z*',
    p_alpath  TYPE c LENGTH 255.
SELECTION-SCREEN END OF BLOCK transport.

SELECTION-SCREEN BEGIN OF BLOCK options WITH FRAME TITLE TEXT-002.
  PARAMETERS:
    p_clear   TYPE c LENGTH 1 AS CHECKBOX DEFAULT ' '.
SELECTION-SCREEN END OF BLOCK options.

*----------------------------------------------------------------------*
* Initialization
*----------------------------------------------------------------------*
INITIALIZATION.
  TEXT-001 = 'Transport Backend'.
  TEXT-002 = 'Options'.

*----------------------------------------------------------------------*
* Selection screen validation
*----------------------------------------------------------------------*
AT SELECTION-SCREEN.
  CASE p_trans.
    WHEN 'A'.
      IF p_giturl IS INITIAL.
        MESSAGE 'Git URL is required for abapGit transport' TYPE 'E'.
      ENDIF.
    WHEN 'P'.
      IF p_giturl IS INITIAL.
        MESSAGE 'Git API URL is required for API transport' TYPE 'E'.
      ENDIF.
      IF p_token IS INITIAL.
        MESSAGE 'API token is required for API transport' TYPE 'E'.
      ENDIF.
    WHEN 'F'.
      IF p_alpath IS INITIAL.
        MESSAGE 'AL11 path is required for filedrop transport' TYPE 'E'.
      ENDIF.
    WHEN OTHERS.
      MESSAGE 'Transport must be A (abapGit), P (API) or F (filedrop)' TYPE 'E'.
  ENDCASE.

*----------------------------------------------------------------------*
* Main program
*----------------------------------------------------------------------*
START-OF-SELECTION.
  PERFORM check_tables.
  PERFORM write_config.
  PERFORM verify_config.

*----------------------------------------------------------------------*
* FORM check_tables
* Verify that the required ZDOC_AGENT_* tables exist in the DDIC.
* If any table is missing, write an error and stop — the user must
* create them in SE11 before continuing.
*----------------------------------------------------------------------*
FORM check_tables.
  DATA: lv_tabname TYPE dd02l-tabname,
        ls_dd02l   TYPE dd02l.

  WRITE: / 'Checking DDIC table existence...'.

  LOOP AT VALUE #(
    ( `ZDOC_AGENT_CFG`  )
    ( `ZDOC_AGENT_SCAN` )
    ( `ZDOC_AGENT_DEPS` )
  ) INTO DATA(lv_tname).

    " TODO: On BW/4HANA verify that DD02L is accessible.
    " On some systems the DDIC check may require a different API.
    SELECT SINGLE tabname FROM dd02l
      INTO lv_tabname
      WHERE tabname = lv_tname
        AND tabclass = 'TRANSP'.

    IF sy-subrc <> 0.
      WRITE: / '  [MISSING]', lv_tname.
      WRITE: / '  --> Create this table in SE11 before running setup.'.
      WRITE: / '  --> See header comments in this report for field definitions.'.
    ELSE.
      WRITE: / '  [OK]     ', lv_tname.
    ENDIF.
  ENDLOOP.

  WRITE: /.
ENDFORM.

*----------------------------------------------------------------------*
* FORM write_config
* Upsert all selection-screen parameters into ZDOC_AGENT_CFG.
* Uses MODIFY (INSERT OR UPDATE) so the program is idempotent.
*----------------------------------------------------------------------*
FORM write_config.
  DATA: lt_entries TYPE STANDARD TABLE OF ty_cfg_entry,
        ls_entry   TYPE ty_cfg_entry.

  WRITE: / 'Writing configuration to ZDOC_AGENT_CFG...'.

  " Clear existing config if checkbox selected
  IF p_clear = 'X'.
    DELETE FROM zdoc_agent_cfg WHERE mandt = sy-mandt.
    IF sy-subrc = 0.
      WRITE: / '  Cleared existing config entries.'.
    ENDIF.
  ENDIF.

  " Build config entries from selection-screen values
  ls_entry-mandt = sy-mandt.

  ls_entry-cfg_key   = 'TRANSPORT_BACKEND'.
  ls_entry-cfg_value = p_trans.
  APPEND ls_entry TO lt_entries.

  IF p_giturl IS NOT INITIAL.
    ls_entry-cfg_key   = 'GIT_URL'.
    ls_entry-cfg_value = p_giturl.
    APPEND ls_entry TO lt_entries.
  ENDIF.

  IF p_token IS NOT INITIAL.
    " NOTE: The token is stored in plain text in ZDOC_AGENT_CFG.
    " In production this should be encrypted or stored in the SAP
    " Secure Storage (SSF / credential store) and referenced by ID.
    ls_entry-cfg_key   = 'API_TOKEN'.
    ls_entry-cfg_value = p_token.
    APPEND ls_entry TO lt_entries.
  ENDIF.

  IF p_nsfiltr IS NOT INITIAL.
    ls_entry-cfg_key   = 'NAMESPACE_FILTER'.
    ls_entry-cfg_value = p_nsfiltr.
    APPEND ls_entry TO lt_entries.
  ELSE.
    ls_entry-cfg_key   = 'NAMESPACE_FILTER'.
    ls_entry-cfg_value = 'Z*'.
    APPEND ls_entry TO lt_entries.
  ENDIF.

  IF p_alpath IS NOT INITIAL.
    ls_entry-cfg_key   = 'AL11_PATH'.
    ls_entry-cfg_value = p_alpath.
    APPEND ls_entry TO lt_entries.
  ENDIF.

  " Write transport backend label for readability
  DATA(lv_backend_label) = SWITCH #( p_trans
    WHEN 'A' THEN 'abapGit'
    WHEN 'P' THEN 'API (GitHub/Gitea)'
    WHEN 'F' THEN 'File Drop (AL11)'
    ELSE          'Unknown' ).
  ls_entry-cfg_key   = 'TRANSPORT_LABEL'.
  ls_entry-cfg_value = lv_backend_label.
  APPEND ls_entry TO lt_entries.

  " Record the setup timestamp
  DATA: lv_ts TYPE timestamp.
  GET TIME STAMP FIELD lv_ts.
  ls_entry-cfg_key   = 'SETUP_TIMESTAMP'.
  ls_entry-cfg_value = |{ lv_ts }|.
  APPEND ls_entry TO lt_entries.

  " MODIFY performs INSERT or UPDATE based on primary key
  MODIFY zdoc_agent_cfg FROM TABLE lt_entries.
  IF sy-subrc = 0.
    WRITE: / '  Wrote', lines( lt_entries ), 'config entries.'.
  ELSE.
    WRITE: / '  [ERROR] Failed to write config — check table exists and has correct structure.'.
    WRITE: / '          sy-subrc =', sy-subrc.
  ENDIF.

  WRITE: /.
ENDFORM.

*----------------------------------------------------------------------*
* FORM verify_config
* Read back what was stored and display it, masking the token.
*----------------------------------------------------------------------*
FORM verify_config.
  DATA: lt_cfg  TYPE STANDARD TABLE OF ty_cfg_entry,
        ls_cfg  TYPE ty_cfg_entry.

  WRITE: / 'Stored configuration:'.
  WRITE: / SY-ULINE(60).

  SELECT mandt cfg_key cfg_value FROM zdoc_agent_cfg
    INTO TABLE lt_cfg
    WHERE mandt = sy-mandt
    ORDER BY cfg_key.

  IF sy-subrc <> 0 OR lines( lt_cfg ) = 0.
    WRITE: / '  No entries found — table may not exist or MODIFY failed.'.
    RETURN.
  ENDIF.

  LOOP AT lt_cfg INTO ls_cfg.
    DATA(lv_display_value) = ls_cfg-cfg_value.
    " Mask token in output
    IF ls_cfg-cfg_key = 'API_TOKEN' AND strlen( lv_display_value ) > 4.
      lv_display_value = |{ lv_display_value(4) }****(masked)****|.
    ENDIF.
    WRITE: / |  { ls_cfg-cfg_key WIDTH = 25 } : { lv_display_value }|.
  ENDLOOP.

  WRITE: / SY-ULINE(60).
  WRITE: /.
  WRITE: / 'Setup complete. Run Z_DOC_AGENT_SCAN to start scanning.'.
ENDFORM.
