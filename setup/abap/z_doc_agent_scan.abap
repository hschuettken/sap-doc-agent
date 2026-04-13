*&---------------------------------------------------------------------*
*& Report Z_DOC_AGENT_SCAN
*&---------------------------------------------------------------------*
*& Purpose: Crawl BW/4HANA objects starting from selected top-level
*&          providers, extract source code + metadata, detect
*&          dependencies, and push results to the configured transport
*&          backend (API / file-drop / abapGit stub).
*&
*& Requires: ZDOC_AGENT_CFG, ZDOC_AGENT_SCAN, ZDOC_AGENT_DEPS
*&           (create in SE11 — see z_doc_agent_setup.abap header)
*&
*& Tested against: BW/4HANA 2.0 SP08 (table names may vary on older
*&                 releases — TODO markers identify verification points)
*&---------------------------------------------------------------------*
REPORT z_doc_agent_scan.

*----------------------------------------------------------------------*
* Type pool references
*----------------------------------------------------------------------*
" TODO: Check whether ABAP_CHAR255 is available on target system;
"       replace with explicit C 255 LENGTH if not.

*----------------------------------------------------------------------*
* Global types
*----------------------------------------------------------------------*
TYPES:
  " ---- Config --------------------------------------------------------
  BEGIN OF ty_config,
    transport_backend TYPE c LENGTH 1,
    git_url           TYPE c LENGTH 255,
    api_token         TYPE c LENGTH 255,
    namespace_filter  TYPE c LENGTH 30,
    al11_path         TYPE c LENGTH 255,
  END OF ty_config,

  " ---- Scan result ---------------------------------------------------
  BEGIN OF ty_scan_row,
    mandt        TYPE mandt,
    object_key   TYPE c LENGTH 60,
    object_type  TYPE c LENGTH 20,
    description  TYPE c LENGTH 255,
    package      TYPE c LENGTH 30,
    owner        TYPE c LENGTH 12,
    last_scan    TYPE dec15,            " ABAP TIMESTAMP as DEC 15
    content_hash TYPE c LENGTH 64,
    source_code  TYPE string,
    metadata     TYPE string,
  END OF ty_scan_row,

  tt_scan_rows TYPE STANDARD TABLE OF ty_scan_row WITH KEY object_key,

  " ---- Dependency ----------------------------------------------------
  BEGIN OF ty_dep_row,
    mandt      TYPE mandt,
    source_key TYPE c LENGTH 60,
    target_key TYPE c LENGTH 60,
    dep_type   TYPE c LENGTH 20,
  END OF ty_dep_row,

  tt_dep_rows TYPE STANDARD TABLE OF ty_dep_row,

  " ---- Queue entry ---------------------------------------------------
  BEGIN OF ty_queue_entry,
    object_key  TYPE c LENGTH 60,
    object_type TYPE c LENGTH 20,
    depth       TYPE i,
  END OF ty_queue_entry,

  tt_queue TYPE STANDARD TABLE OF ty_queue_entry.

*----------------------------------------------------------------------*
* Selection screen
*----------------------------------------------------------------------*
SELECTION-SCREEN BEGIN OF BLOCK provider WITH FRAME TITLE TEXT-100.
  SELECT-OPTIONS: s_provdr FOR ( VALUE #( ) ) NO INTERVALS.
  PARAMETERS:
    p_depth  TYPE i DEFAULT 99,
    p_dryrun TYPE c LENGTH 1 AS CHECKBOX DEFAULT ' '.
SELECTION-SCREEN END OF BLOCK provider.

SELECTION-SCREEN BEGIN OF BLOCK filters WITH FRAME TITLE TEXT-101.
  PARAMETERS:
    p_types  TYPE c LENGTH 100 DEFAULT 'ADSO,CMP,TRAN,IOBJ,CHAIN,DS,CLASS,FM,TABL'.
SELECTION-SCREEN END OF BLOCK filters.

*----------------------------------------------------------------------*
* Global data
*----------------------------------------------------------------------*
DATA:
  gs_config   TYPE ty_config,
  gt_scan     TYPE tt_scan_rows,
  gt_deps     TYPE tt_dep_rows,
  gt_queue    TYPE tt_queue,
  gt_visited  TYPE SORTED TABLE OF c LENGTH 60 WITH UNIQUE KEY table_line,
  gv_scan_ts  TYPE timestamp.

*----------------------------------------------------------------------*
* Initialization
*----------------------------------------------------------------------*
INITIALIZATION.
  TEXT-100 = 'Provider Selection'.
  TEXT-101 = 'Object Type Filters'.

*----------------------------------------------------------------------*
* Main
*----------------------------------------------------------------------*
START-OF-SELECTION.
  PERFORM load_config.
  PERFORM init_queue.
  PERFORM run_crawl.
  IF p_dryrun = ' '.
    PERFORM persist_results.
    PERFORM push_output.
  ELSE.
    PERFORM dry_run_report.
  ENDIF.

*----------------------------------------------------------------------*
* FORM load_config
*----------------------------------------------------------------------*
FORM load_config.
  DATA: lv_value TYPE c LENGTH 255.

  WRITE: / 'Loading configuration from ZDOC_AGENT_CFG...'.

  " Helper macro to read one key
  DEFINE read_cfg.
    SELECT SINGLE cfg_value FROM zdoc_agent_cfg
      INTO lv_value
      WHERE mandt = sy-mandt AND cfg_key = &1.
    IF sy-subrc = 0.
      &2 = lv_value.
    ENDIF.
  END-OF-DEFINITION.

  read_cfg 'TRANSPORT_BACKEND' gs_config-transport_backend.
  read_cfg 'GIT_URL'           gs_config-git_url.
  read_cfg 'API_TOKEN'         gs_config-api_token.
  read_cfg 'NAMESPACE_FILTER'  gs_config-namespace_filter.
  read_cfg 'AL11_PATH'         gs_config-al11_path.

  IF gs_config-transport_backend IS INITIAL.
    gs_config-transport_backend = 'P'.
    WRITE: / '  No backend configured — defaulting to API.'.
  ENDIF.
  IF gs_config-namespace_filter IS INITIAL.
    gs_config-namespace_filter = 'Z*'.
  ENDIF.

  WRITE: / |  Backend : { gs_config-transport_backend }|.
  WRITE: / |  NS filter: { gs_config-namespace_filter }|.
  WRITE: /.

  GET TIME STAMP FIELD gv_scan_ts.
ENDFORM.

*----------------------------------------------------------------------*
* FORM init_queue
* Seed the crawl queue with the providers entered on the selection
* screen. If no selection was made, abort with a message.
*----------------------------------------------------------------------*
FORM init_queue.
  DATA: ls_entry TYPE ty_queue_entry.

  IF s_provdr[] IS INITIAL.
    WRITE: / 'No providers selected — aborting.'.
    STOP.
  ENDIF.

  LOOP AT s_provdr INTO DATA(ls_sel).
    IF ls_sel-low IS NOT INITIAL.
      ls_entry-object_key  = ls_sel-low.
      ls_entry-object_type = 'PROVIDER'.   " resolved during crawl
      ls_entry-depth       = 0.
      APPEND ls_entry TO gt_queue.
    ENDIF.
  ENDLOOP.

  WRITE: / |Queued { lines( gt_queue ) } seed provider(s).|.
  WRITE: /.
ENDFORM.

*----------------------------------------------------------------------*
* FORM run_crawl
* Main BFS loop. Pops entries from gt_queue, dispatches to the
* appropriate extractor, then enqueues newly discovered dependencies.
*----------------------------------------------------------------------*
FORM run_crawl.
  DATA: ls_entry   TYPE ty_queue_entry,
        ls_scan    TYPE ty_scan_row,
        lt_newdeps TYPE tt_dep_rows.

  DATA(lv_total_processed) = 0.

  WHILE lines( gt_queue ) > 0.
    " Pop first entry
    ls_entry = gt_queue[ 1 ].
    DELETE gt_queue INDEX 1.

    " Depth guard
    IF ls_entry-depth > p_depth.
      CONTINUE.
    ENDIF.

    " Already visited?
    READ TABLE gt_visited WITH KEY table_line = ls_entry-object_key
      TRANSPORTING NO FIELDS.
    IF sy-subrc = 0.
      CONTINUE.
    ENDIF.
    INSERT ls_entry-object_key INTO TABLE gt_visited.

    " Namespace filter
    IF NOT ls_entry-object_key CP gs_config-namespace_filter AND
       NOT ls_entry-object_key CP 'Y*'.
      " TODO: on some systems Z* objects use /namespace/ prefix —
      "       adjust filter logic accordingly.
      CONTINUE.
    ENDIF.

    " Show progress
    lv_total_processed = lv_total_processed + 1.
    cl_progress_indicator=>progress_indicate(
      i_text               = |Scanning { ls_entry-object_key } ({ ls_entry-object_type })|
      i_processed          = lv_total_processed
      i_total              = lv_total_processed + lines( gt_queue )
      i_output_immediately = 'X' ).

    " Dispatch to correct extractor based on type
    CLEAR: ls_scan, lt_newdeps.
    ls_scan-mandt      = sy-mandt.
    ls_scan-object_key = ls_entry-object_key.
    ls_scan-last_scan  = gv_scan_ts.

    CASE ls_entry-object_type.
      WHEN 'PROVIDER' OR 'ADSO'.
        PERFORM extract_adso
          USING    ls_entry-object_key
          CHANGING ls_scan lt_newdeps.

      WHEN 'CMP'.
        PERFORM extract_composite_provider
          USING    ls_entry-object_key
          CHANGING ls_scan lt_newdeps.

      WHEN 'TRAN'.
        PERFORM extract_transformation
          USING    ls_entry-object_key
          CHANGING ls_scan lt_newdeps.

      WHEN 'IOBJ'.
        PERFORM extract_infoobject
          USING    ls_entry-object_key
          CHANGING ls_scan lt_newdeps.

      WHEN 'CHAIN'.
        PERFORM extract_process_chain
          USING    ls_entry-object_key
          CHANGING ls_scan lt_newdeps.

      WHEN 'DS'.
        PERFORM extract_datasource
          USING    ls_entry-object_key
          CHANGING ls_scan lt_newdeps.

      WHEN 'CLASS'.
        PERFORM extract_class
          USING    ls_entry-object_key
          CHANGING ls_scan lt_newdeps.

      WHEN 'FM'.
        PERFORM extract_function_module
          USING    ls_entry-object_key
          CHANGING ls_scan lt_newdeps.

      WHEN 'TABL'.
        PERFORM extract_table
          USING    ls_entry-object_key
          CHANGING ls_scan lt_newdeps.

      WHEN OTHERS.
        " Try ADSO as default for unknown provider-type seeds
        PERFORM extract_adso
          USING    ls_entry-object_key
          CHANGING ls_scan lt_newdeps.
    ENDCASE.

    " Skip if extractor produced no data (object not found)
    IF ls_scan-object_type IS INITIAL.
      CONTINUE.
    ENDIF.

    " Compute a simple content hash (FNV-1a style via string concat)
    " TODO: Replace with a proper SHA-256 if ABAP_CRYPTO or
    "       CL_SEC_SXML_WRITER is available on the target system.
    ls_scan-content_hash = CONV #(
      cl_abap_message_digest=>calculate_hash_for_char(
        if_algorithm = 'SHA256'
        if_data      = |{ ls_scan-source_code }{ ls_scan-metadata }|
      ) ) ##TODO.
    " Fallback if hash not available (will be overwritten if API works):
    IF ls_scan-content_hash IS INITIAL.
      DATA(lv_seed) = |{ ls_scan-object_key }{ gv_scan_ts }|.
      ls_scan-content_hash = lv_seed(60).
    ENDIF.

    " Store scan result
    APPEND ls_scan TO gt_scan.

    " Store dependencies and enqueue their targets
    LOOP AT lt_newdeps INTO DATA(ls_dep).
      ls_dep-mandt = sy-mandt.
      APPEND ls_dep TO gt_deps.

      " Enqueue target if not yet visited and within depth
      READ TABLE gt_visited WITH KEY table_line = ls_dep-target_key
        TRANSPORTING NO FIELDS.
      IF sy-subrc <> 0 AND ls_entry-depth + 1 <= p_depth.
        DATA(ls_new_entry) = VALUE ty_queue_entry(
          object_key  = ls_dep-target_key
          object_type = ls_dep-dep_type   " dep_type doubles as object type hint
          depth       = ls_entry-depth + 1 ).
        " Normalize type hint: if dep_type is a relation label, guess object type
        CASE ls_dep-dep_type.
          WHEN 'USES_FM'.     ls_new_entry-object_type = 'FM'.
          WHEN 'CALLS_CLASS'. ls_new_entry-object_type = 'CLASS'.
          WHEN 'READS_TABLE'. ls_new_entry-object_type = 'TABL'.
          WHEN 'USES_IOBJ'.   ls_new_entry-object_type = 'IOBJ'.
          WHEN 'HAS_TRAN'.    ls_new_entry-object_type = 'TRAN'.
          WHEN 'HAS_DS'.      ls_new_entry-object_type = 'DS'.
          WHEN 'CHAIN_STEP'.  ls_new_entry-object_type = 'CHAIN'.
          WHEN 'USES_CMP'.    ls_new_entry-object_type = 'CMP'.
        ENDCASE.
        APPEND ls_new_entry TO gt_queue.
      ENDIF.
    ENDLOOP.

    WRITE: / |  Scanned: { ls_scan-object_type WIDTH = 8 } { ls_scan-object_key }|.
  ENDWHILE.

  WRITE: /.
  WRITE: / |Crawl complete. Objects: { lines( gt_scan ) }  Dependencies: { lines( gt_deps ) }|.
  WRITE: /.
ENDFORM.

*----------------------------------------------------------------------*
* FORM extract_adso
* Extract metadata for an Advanced DSO from RSOADSO / RSOADSOT.
* Also discovers transformations and data sources that feed this ADSO.
*----------------------------------------------------------------------*
FORM extract_adso
  USING    iv_key   TYPE c
  CHANGING cs_scan  TYPE ty_scan_row
           ct_deps  TYPE tt_dep_rows.

  " TODO: Verify table names on BW/4HANA 2.0 — RSOADSO is the central
  "       ADSO attribute table on BW/4HANA; earlier BW versions may use
  "       RSDCUBE for virtual providers.
  TYPES:
    BEGIN OF ty_adso,
      adsonm   TYPE c LENGTH 30,
      objvers  TYPE c LENGTH 1,
      txtlg    TYPE c LENGTH 60,
      devclass TYPE c LENGTH 30,
      aenam    TYPE c LENGTH 12,
    END OF ty_adso.

  DATA: ls_adso TYPE ty_adso.

  SELECT SINGLE
      a~adsonm a~objvers
      t~txtlg
      a~devclass a~aenam
    FROM rsoadso AS a
    LEFT OUTER JOIN rsoadsot AS t
      ON  t~adsonm  = a~adsonm
      AND t~objvers = a~objvers
      AND t~langu   = sy-langu
    INTO CORRESPONDING FIELDS OF ls_adso
    WHERE a~adsonm  = iv_key
      AND a~objvers = 'A'.   " A = active version

  IF sy-subrc <> 0.
    RETURN.   " Not an ADSO — let caller try other extractors
  ENDIF.

  cs_scan-object_type = 'ADSO'.
  cs_scan-description = ls_adso-txtlg.
  cs_scan-package     = ls_adso-devclass.
  cs_scan-owner       = ls_adso-aenam.

  " Build JSON metadata
  cs_scan-metadata = |\{"type":"ADSO","name":"{ iv_key }","desc":"{ ls_adso-txtlg }","package":"{ ls_adso-devclass }"\}|.

  " Source code: ADSOs don't have ABAP source — store field list as pseudo-source
  DATA: lt_fields TYPE STANDARD TABLE OF rsoadsoiobj,
        lv_field_list TYPE string.

  " TODO: Verify RSOADSOIOBJ field name for key/nav attributes on your version
  SELECT adsonm iobjenm keyfig FROM rsoadsoiobj
    INTO TABLE lt_fields
    WHERE adsonm  = iv_key
      AND objvers = 'A'.

  LOOP AT lt_fields INTO DATA(ls_fld).
    lv_field_list = lv_field_list && |{ ls_fld-iobjenm }|.
    IF sy-tabix < lines( lt_fields ).
      lv_field_list = lv_field_list && |, |.
    ENDIF.
  ENDLOOP.
  cs_scan-source_code = |-- ADSO fields --\n{ lv_field_list }|.

  " Discover feeding transformations (RSTRAN: SOURCENAME = ADSO)
  SELECT trfn sourcetype sourcename targettype targetname
    FROM rstran
    INTO TABLE @DATA(lt_trans)
    WHERE targetname = @iv_key
      AND objvers    = 'A'.

  LOOP AT lt_trans INTO DATA(ls_tran).
    APPEND VALUE #(
      source_key = iv_key
      target_key = ls_tran-trfn
      dep_type   = 'HAS_TRAN'
    ) TO ct_deps.
  ENDLOOP.

  " Discover package
  PERFORM get_package USING 'ADSO' iv_key CHANGING cs_scan-package.
ENDFORM.

*----------------------------------------------------------------------*
* FORM extract_composite_provider
* Extract CompositeProvider metadata from RSDCUBE / RSDCUBET.
* CompositeProviders are stored as InfoProviders of type CMP.
*----------------------------------------------------------------------*
FORM extract_composite_provider
  USING    iv_key   TYPE c
  CHANGING cs_scan  TYPE ty_scan_row
           ct_deps  TYPE tt_dep_rows.

  " TODO: On BW/4HANA, CompositeProviders may appear in RSOPACPR
  "       rather than RSDCUBE depending on BW version.
  TYPES:
    BEGIN OF ty_cmp,
      infocube TYPE c LENGTH 30,
      txtlg    TYPE c LENGTH 60,
      devclass TYPE c LENGTH 30,
      aenam    TYPE c LENGTH 12,
    END OF ty_cmp.

  DATA: ls_cmp TYPE ty_cmp.

  SELECT SINGLE
      c~infocube
      t~txtlg
      c~devclass c~aenam
    FROM rsdcube AS c
    LEFT OUTER JOIN rsdcubet AS t
      ON  t~infocube = c~infocube
      AND t~objvers  = c~objvers
      AND t~langu    = sy-langu
    INTO CORRESPONDING FIELDS OF ls_cmp
    WHERE c~infocube = iv_key
      AND c~objvers  = 'A'.

  IF sy-subrc <> 0.
    RETURN.
  ENDIF.

  cs_scan-object_type = 'CMP'.
  cs_scan-description = ls_cmp-txtlg.
  cs_scan-package     = ls_cmp-devclass.
  cs_scan-owner       = ls_cmp-aenam.
  cs_scan-metadata    = |\{"type":"CMP","name":"{ iv_key }","desc":"{ ls_cmp-txtlg }"\}|.
  cs_scan-source_code = |-- CompositeProvider: { iv_key }|.

  " Discover member providers (RSDCUBEMULTI or RSOPAMULTI)
  " TODO: Verify correct join table name on target BW version
  SELECT partprov FROM rsdcubemulti
    INTO TABLE @DATA(lt_members)
    WHERE infocube = @iv_key
      AND objvers  = 'A'.

  LOOP AT lt_members INTO DATA(ls_m).
    APPEND VALUE #(
      source_key = iv_key
      target_key = ls_m-partprov
      dep_type   = 'HAS_MEMBER'
    ) TO ct_deps.
  ENDLOOP.

  PERFORM get_package USING 'CUBE' iv_key CHANGING cs_scan-package.
ENDFORM.

*----------------------------------------------------------------------*
* FORM extract_transformation
* Extract transformation header and optionally the ABAP source of
* each start/end routine and field-level routine.
*----------------------------------------------------------------------*
FORM extract_transformation
  USING    iv_key   TYPE c
  CHANGING cs_scan  TYPE ty_scan_row
           ct_deps  TYPE tt_dep_rows.

  " TODO: RSTRAN primary key is TRFN (transformation ID) — confirm
  "       whether the caller passes TRFN or a human-readable name.
  TYPES:
    BEGIN OF ty_tran,
      trfn       TYPE c LENGTH 32,
      sourcename TYPE c LENGTH 30,
      targetname TYPE c LENGTH 30,
      sourcetype TYPE c LENGTH 4,
      targettype TYPE c LENGTH 4,
      devclass   TYPE c LENGTH 30,
      aenam      TYPE c LENGTH 12,
    END OF ty_tran.

  DATA: ls_tran TYPE ty_tran.

  SELECT SINGLE trfn sourcename targetname sourcetype targettype devclass aenam
    FROM rstran
    INTO CORRESPONDING FIELDS OF ls_tran
    WHERE trfn    = iv_key
      AND objvers = 'A'.

  IF sy-subrc <> 0.
    RETURN.
  ENDIF.

  cs_scan-object_type = 'TRAN'.
  cs_scan-description = |{ ls_tran-sourcename } -> { ls_tran-targetname }|.
  cs_scan-package     = ls_tran-devclass.
  cs_scan-owner       = ls_tran-aenam.

  " Read routine source code from the generated include
  " Transformation routines live in includes named LRSTT<trfn>...
  " TODO: Verify exact include naming convention on target system.
  DATA: lv_source_all TYPE string,
        lt_source     TYPE STANDARD TABLE OF string.

  " Read start routine (include pattern varies; using known BW pattern)
  DATA(lv_start_include) = |LRSTS{ iv_key(10) }|.    " stub naming
  READ REPORT lv_start_include INTO lt_source.
  IF sy-subrc = 0.
    LOOP AT lt_source INTO DATA(lv_line).
      lv_source_all = lv_source_all && lv_line && cl_abap_char_utilities=>newline.
    ENDLOOP.
  ENDIF.

  " Read step routines from RSTRANSTEPROUT
  SELECT stepno routtype inclname
    FROM rstransteprout
    INTO TABLE @DATA(lt_steps)
    WHERE trfn    = @iv_key
      AND objvers = 'A'.

  LOOP AT lt_steps INTO DATA(ls_step).
    IF ls_step-inclname IS NOT INITIAL.
      CLEAR lt_source.
      READ REPORT ls_step-inclname INTO lt_source.
      IF sy-subrc = 0.
        lv_source_all = lv_source_all &&
          |*-- Step { ls_step-stepno } ({ ls_step-routtype }) --*\n|.
        LOOP AT lt_source INTO lv_line.
          lv_source_all = lv_source_all && lv_line && cl_abap_char_utilities=>newline.
        ENDLOOP.
      ENDIF.
    ENDIF.
  ENDLOOP.

  cs_scan-source_code = lv_source_all.
  cs_scan-metadata    = |\{"type":"TRAN","id":"{ iv_key }","src":"{ ls_tran-sourcename }","tgt":"{ ls_tran-targetname }"\}|.

  " Dependencies: source and target providers
  APPEND VALUE #(
    source_key = iv_key
    target_key = ls_tran-sourcename
    dep_type   = 'HAS_DS'
  ) TO ct_deps.

  APPEND VALUE #(
    source_key = iv_key
    target_key = ls_tran-targetname
    dep_type   = 'FEEDS_ADSO'
  ) TO ct_deps.
ENDFORM.

*----------------------------------------------------------------------*
* FORM extract_infoobject
* Extract InfoObject (characteristic / key figure) metadata.
*----------------------------------------------------------------------*
FORM extract_infoobject
  USING    iv_key   TYPE c
  CHANGING cs_scan  TYPE ty_scan_row
           ct_deps  TYPE tt_dep_rows.

  TYPES:
    BEGIN OF ty_iobj,
      iobjnm   TYPE c LENGTH 30,
      objvers  TYPE c LENGTH 1,
      txtlg    TYPE c LENGTH 60,
      devclass TYPE c LENGTH 30,
      aenam    TYPE c LENGTH 12,
      ioobjtp  TYPE c LENGTH 1,    " C=char, K=keyfig, T=time, U=unit
    END OF ty_iobj.

  DATA: ls_iobj TYPE ty_iobj.

  SELECT SINGLE
      i~iobjnm i~objvers i~ioobjtp i~devclass i~aenam
      t~txtlg
    FROM rsdiobj AS i
    LEFT OUTER JOIN rsdiobjt AS t
      ON  t~iobjnm  = i~iobjnm
      AND t~objvers = i~objvers
      AND t~langu   = sy-langu
    INTO CORRESPONDING FIELDS OF ls_iobj
    WHERE i~iobjnm  = iv_key
      AND i~objvers = 'A'.

  IF sy-subrc <> 0.
    RETURN.
  ENDIF.

  cs_scan-object_type = 'IOBJ'.
  cs_scan-description = ls_iobj-txtlg.
  cs_scan-package     = ls_iobj-devclass.
  cs_scan-owner       = ls_iobj-aenam.
  cs_scan-source_code = |-- InfoObject { iv_key } type { ls_iobj-ioobjtp }|.
  cs_scan-metadata    = |\{"type":"IOBJ","name":"{ iv_key }","iotype":"{ ls_iobj-ioobjtp }","desc":"{ ls_iobj-txtlg }"\}|.

  " TODO: Optionally follow compounding (RSDIOBJCMP) to discover
  "       parent InfoObjects.
ENDFORM.

*----------------------------------------------------------------------*
* FORM extract_process_chain
* Extract Process Chain definition and enumerate steps as dependencies.
*----------------------------------------------------------------------*
FORM extract_process_chain
  USING    iv_key   TYPE c
  CHANGING cs_scan  TYPE ty_scan_row
           ct_deps  TYPE tt_dep_rows.

  TYPES:
    BEGIN OF ty_chain,
      chain_id TYPE c LENGTH 30,
      txtlg    TYPE c LENGTH 60,
      devclass TYPE c LENGTH 30,
      aenam    TYPE c LENGTH 12,
    END OF ty_chain.

  DATA: ls_chain TYPE ty_chain.

  " RSPCCHAIN: process chain header
  " TODO: Verify exact field list available on BW/4HANA 2.0
  SELECT SINGLE chain_id devclass aenam
    FROM rspcchain
    INTO CORRESPONDING FIELDS OF ls_chain
    WHERE chain_id = iv_key.

  IF sy-subrc <> 0.
    RETURN.
  ENDIF.

  " Get long text from RSPCCHAINDESCR or RSPCCHAINTXT
  " TODO: Verify text table name on target system
  SELECT SINGLE txtlg FROM rspcchainattr
    INTO ls_chain-txtlg
    WHERE chain_id = iv_key
      AND langu    = sy-langu.

  cs_scan-object_type = 'CHAIN'.
  cs_scan-description = ls_chain-txtlg.
  cs_scan-package     = ls_chain-devclass.
  cs_scan-owner       = ls_chain-aenam.
  cs_scan-source_code = |-- Process Chain: { iv_key }|.

  " Enumerate chain steps (variant/process names)
  " TODO: RSPCSTEPLOG or equivalent; verify table name
  SELECT logchain variantname type_prog
    FROM rspcstep
    INTO TABLE @DATA(lt_steps)
    WHERE logchain = @iv_key.

  DATA(lv_step_list) = ||.
  LOOP AT lt_steps INTO DATA(ls_step).
    lv_step_list = lv_step_list && ls_step-variantname && `, `.
    APPEND VALUE #(
      source_key = iv_key
      target_key = ls_step-variantname
      dep_type   = 'CHAIN_STEP'
    ) TO ct_deps.
  ENDLOOP.

  cs_scan-metadata = |\{"type":"CHAIN","id":"{ iv_key }","steps":{ lines( lt_steps ) }\}|.
  cs_scan-source_code = |{ cs_scan-source_code }\nSteps: { lv_step_list }|.

  PERFORM get_package USING 'RSPC' iv_key CHANGING cs_scan-package.
ENDFORM.

*----------------------------------------------------------------------*
* FORM extract_datasource
* Extract DataSource (RSDS) metadata.
*----------------------------------------------------------------------*
FORM extract_datasource
  USING    iv_key   TYPE c
  CHANGING cs_scan  TYPE ty_scan_row
           ct_deps  TYPE tt_dep_rows.

  TYPES:
    BEGIN OF ty_ds,
      datasource TYPE c LENGTH 60,
      logsys     TYPE c LENGTH 10,
      txtlg      TYPE c LENGTH 60,
      devclass   TYPE c LENGTH 30,
      aenam      TYPE c LENGTH 12,
    END OF ty_ds.

  DATA: ls_ds TYPE ty_ds.

  " RSDS: one row per DataSource / logical system combination
  " TODO: Confirm RSDS key fields for BW/4HANA vs classic BW
  SELECT SINGLE d~datasource d~logsys d~devclass d~aenam
      t~txtlg
    FROM rsds AS d
    LEFT OUTER JOIN rsdst AS t
      ON  t~datasource = d~datasource
      AND t~logsys     = d~logsys
      AND t~langu      = sy-langu
    INTO CORRESPONDING FIELDS OF ls_ds
    WHERE d~datasource = iv_key.

  IF sy-subrc <> 0.
    RETURN.
  ENDIF.

  cs_scan-object_type = 'DS'.
  cs_scan-description = ls_ds-txtlg.
  cs_scan-package     = ls_ds-devclass.
  cs_scan-owner       = ls_ds-aenam.
  cs_scan-source_code = |-- DataSource: { iv_key } (logsys: { ls_ds-logsys })|.
  cs_scan-metadata    = |\{"type":"DS","name":"{ iv_key }","logsys":"{ ls_ds-logsys }","desc":"{ ls_ds-txtlg }"\}|.
ENDFORM.

*----------------------------------------------------------------------*
* FORM extract_class
* Extract ABAP class source and component list.
*----------------------------------------------------------------------*
FORM extract_class
  USING    iv_key   TYPE c
  CHANGING cs_scan  TYPE ty_scan_row
           ct_deps  TYPE tt_dep_rows.

  DATA: lt_source TYPE STANDARD TABLE OF string,
        lv_source TYPE string.

  " Read the global class include (the main pool)
  READ REPORT iv_key INTO lt_source.
  IF sy-subrc <> 0.
    " Try the local class include variant
    DATA(lv_class_pool) = iv_key && `=====CP`.
    READ REPORT lv_class_pool INTO lt_source.
    IF sy-subrc <> 0.
      RETURN.
    ENDIF.
  ENDIF.

  LOOP AT lt_source INTO DATA(lv_line).
    lv_source = lv_source && lv_line && cl_abap_char_utilities=>newline.
  ENDLOOP.

  " Also read all method implementations
  DATA: lt_compo   TYPE STANDARD TABLE OF seocompo,
        lv_methsrc TYPE string.

  SELECT cpdkey cpname cmptype FROM seocompo
    INTO TABLE lt_compo
    WHERE cpdkey = iv_key.

  LOOP AT lt_compo INTO DATA(ls_compo).
    IF ls_compo-cmptype = '1'.   " 1 = method
      DATA(lv_meth_include) = iv_key && `=====` && ls_compo-cpname && `=`.
      CLEAR lt_source.
      READ REPORT lv_meth_include INTO lt_source.
      IF sy-subrc = 0.
        lv_methsrc = lv_methsrc && |*-- METHOD { ls_compo-cpname } --*\n|.
        LOOP AT lt_source INTO lv_line.
          lv_methsrc = lv_methsrc && lv_line && cl_abap_char_utilities=>newline.
        ENDLOOP.
      ENDIF.
    ENDIF.
  ENDLOOP.

  cs_scan-object_type = 'CLASS'.
  cs_scan-source_code = lv_source && lv_methsrc.
  cs_scan-metadata    = |\{"type":"CLASS","name":"{ iv_key }","methods":{ lines( lt_compo ) }\}|.

  " Get description from SEOCLASS
  SELECT SINGLE descript FROM seoclass
    INTO cs_scan-description
    WHERE clsname = iv_key.

  " Get package
  PERFORM get_package USING 'CLAS' iv_key CHANGING cs_scan-package.

  " Detect FM calls / class instantiations as dependencies
  PERFORM extract_code_refs USING lv_source iv_key CHANGING ct_deps.
ENDFORM.

*----------------------------------------------------------------------*
* FORM extract_function_module
* Read FM source from the function group include.
*----------------------------------------------------------------------*
FORM extract_function_module
  USING    iv_key   TYPE c
  CHANGING cs_scan  TYPE ty_scan_row
           ct_deps  TYPE tt_dep_rows.

  DATA: lv_funcname TYPE rs38l-name,
        lv_progname TYPE tfdir-pname,
        lt_source   TYPE STANDARD TABLE OF string,
        lv_source   TYPE string.

  lv_funcname = iv_key.

  " Get include program from TFDIR
  SELECT SINGLE pname FROM tfdir
    INTO lv_progname
    WHERE funcname = lv_funcname.

  IF sy-subrc <> 0.
    RETURN.
  ENDIF.

  READ REPORT lv_progname INTO lt_source.
  LOOP AT lt_source INTO DATA(lv_line).
    lv_source = lv_source && lv_line && cl_abap_char_utilities=>newline.
  ENDLOOP.

  cs_scan-object_type = 'FM'.
  cs_scan-source_code = lv_source.

  " Get short text from FUNCT
  SELECT SINGLE stext FROM funct
    INTO cs_scan-description
    WHERE funcname = lv_funcname
      AND langu    = sy-langu.

  cs_scan-metadata = |\{"type":"FM","name":"{ iv_key }","program":"{ lv_progname }"\}|.

  PERFORM get_package USING 'FUGR' lv_progname CHANGING cs_scan-package.
  PERFORM extract_code_refs USING lv_source iv_key CHANGING ct_deps.
ENDFORM.

*----------------------------------------------------------------------*
* FORM extract_table
* Extract table definition (field list) from DD02L / DD03L.
*----------------------------------------------------------------------*
FORM extract_table
  USING    iv_key   TYPE c
  CHANGING cs_scan  TYPE ty_scan_row
           ct_deps  TYPE tt_dep_rows.

  DATA: ls_dd02 TYPE dd02l,
        lt_dd03 TYPE STANDARD TABLE OF dd03l.

  SELECT SINGLE * FROM dd02l
    INTO ls_dd02
    WHERE tabname = iv_key.

  IF sy-subrc <> 0.
    RETURN.
  ENDIF.

  SELECT * FROM dd03l
    INTO TABLE lt_dd03
    WHERE tabname = iv_key
    ORDER BY position.

  " Build a pseudo-DDL source representation
  DATA(lv_source) = |TABLE { iv_key }:\n|.
  LOOP AT lt_dd03 INTO DATA(ls_fld).
    lv_source = lv_source &&
      |  { ls_fld-fieldname WIDTH = 30 } { ls_fld-datatype }({ ls_fld-leng }) { ls_fld-ddtext }\n|.
  ENDLOOP.

  " Description from DD02T
  SELECT SINGLE ddtext FROM dd02t
    INTO cs_scan-description
    WHERE tabname = iv_key
      AND ddlanguage = sy-langu.

  cs_scan-object_type = 'TABL'.
  cs_scan-source_code = lv_source.
  cs_scan-owner       = ls_dd02-as4user.
  cs_scan-metadata    = |\{"type":"TABL","name":"{ iv_key }","tabclass":"{ ls_dd02-tabclass }","fields":{ lines( lt_dd03 ) }\}|.

  PERFORM get_package USING 'TABL' iv_key CHANGING cs_scan-package.
ENDFORM.

*----------------------------------------------------------------------*
* FORM extract_code_refs
* Scan ABAP source text for CALL FUNCTION, CREATE OBJECT, and
* SELECT...FROM patterns to populate dependency table.
* This is a lightweight heuristic — not a full parser.
*----------------------------------------------------------------------*
FORM extract_code_refs
  USING    iv_source     TYPE string
           iv_source_key TYPE c
  CHANGING ct_deps       TYPE tt_dep_rows.

  DATA: lv_offset TYPE i,
        lv_len    TYPE i,
        lv_match  TYPE string,
        lv_target TYPE c LENGTH 60.

  " Split source into lines for processing
  DATA: lt_lines TYPE STANDARD TABLE OF string.
  SPLIT iv_source AT cl_abap_char_utilities=>newline INTO TABLE lt_lines.

  LOOP AT lt_lines INTO DATA(lv_line).
    DATA(lv_upper) = to_upper( lv_line ).

    " Detect CALL FUNCTION '...'
    FIND REGEX `CALL\s+FUNCTION\s+'([A-Z0-9_/]+)'`
      IN lv_upper
      SUBMATCHES lv_match.
    IF sy-subrc = 0 AND lv_match IS NOT INITIAL.
      lv_target = lv_match.
      CONDENSE lv_target.
      IF lv_target <> iv_source_key.
        APPEND VALUE #(
          source_key = iv_source_key
          target_key = lv_target
          dep_type   = 'USES_FM'
        ) TO ct_deps.
      ENDIF.
    ENDIF.

    " Detect CREATE OBJECT ... TYPE or NEW classname(
    FIND REGEX `NEW\s+([A-Z][A-Z0-9_]+)\s*\(`
      IN lv_upper
      SUBMATCHES lv_match.
    IF sy-subrc = 0 AND lv_match IS NOT INITIAL.
      lv_target = lv_match.
      CONDENSE lv_target.
      APPEND VALUE #(
        source_key = iv_source_key
        target_key = lv_target
        dep_type   = 'CALLS_CLASS'
      ) TO ct_deps.
    ENDIF.

    " Detect SELECT ... FROM tablename
    FIND REGEX `FROM\s+([A-Z][A-Z0-9_]+)`
      IN lv_upper
      SUBMATCHES lv_match.
    IF sy-subrc = 0 AND lv_match IS NOT INITIAL.
      lv_target = lv_match.
      CONDENSE lv_target.
      " Skip obvious non-table keywords
      IF lv_target NA 'WHERE ORDER INTO UNION'.
        APPEND VALUE #(
          source_key = iv_source_key
          target_key = lv_target
          dep_type   = 'READS_TABLE'
        ) TO ct_deps.
      ENDIF.
    ENDIF.
  ENDLOOP.

  " Remove duplicates
  SORT ct_deps BY source_key target_key dep_type.
  DELETE ADJACENT DUPLICATES FROM ct_deps
    COMPARING source_key target_key dep_type.
ENDFORM.

*----------------------------------------------------------------------*
* FORM get_package
* Look up the package (DEVCLASS) for an object via TADIR.
*----------------------------------------------------------------------*
FORM get_package
  USING    iv_pgmid   TYPE tadir-pgmid
           iv_obj_name TYPE c
  CHANGING cv_package TYPE c.

  SELECT SINGLE devclass FROM tadir
    INTO cv_package
    WHERE pgmid    = iv_pgmid
      AND obj_name = iv_obj_name.

  IF sy-subrc <> 0 AND cv_package IS INITIAL.
    cv_package = '$TMP'.   " fallback: local / unassigned
  ENDIF.
ENDFORM.

*----------------------------------------------------------------------*
* FORM persist_results
* MODIFY scan and dependency tables in bulk.
*----------------------------------------------------------------------*
FORM persist_results.
  WRITE: / 'Persisting results to ZDOC_AGENT_SCAN / ZDOC_AGENT_DEPS...'.

  IF lines( gt_scan ) = 0.
    WRITE: / '  Nothing to store.'.
    RETURN.
  ENDIF.

  " Update LAST_SCAN on all rows
  DATA: ls_scan TYPE ty_scan_row.
  LOOP AT gt_scan INTO ls_scan.
    ls_scan-last_scan = gv_scan_ts.
    MODIFY gt_scan FROM ls_scan.
  ENDLOOP.

  MODIFY zdoc_agent_scan FROM TABLE gt_scan.
  IF sy-subrc = 0.
    WRITE: / |  Wrote { lines( gt_scan ) } scan rows.|.
  ELSE.
    WRITE: / '  [ERROR] Failed to write ZDOC_AGENT_SCAN — sy-subrc =', sy-subrc.
  ENDIF.

  IF lines( gt_deps ) > 0.
    MODIFY zdoc_agent_deps FROM TABLE gt_deps.
    IF sy-subrc = 0.
      WRITE: / |  Wrote { lines( gt_deps ) } dependency rows.|.
    ELSE.
      WRITE: / '  [ERROR] Failed to write ZDOC_AGENT_DEPS — sy-subrc =', sy-subrc.
    ENDIF.
  ENDIF.

  WRITE: /.
ENDFORM.

*----------------------------------------------------------------------*
* FORM push_output
* Delegate to the configured transport backend via a factory.
*----------------------------------------------------------------------*
FORM push_output.
  WRITE: / 'Pushing to transport backend...'.

  CASE gs_config-transport_backend.
    WHEN 'A'.
      PERFORM push_abapgit.
    WHEN 'P'.
      PERFORM push_api.
    WHEN 'F'.
      PERFORM push_filedrop.
    WHEN OTHERS.
      WRITE: / '  [ERROR] Unknown backend.'.
  ENDCASE.
ENDFORM.

*----------------------------------------------------------------------*
* FORM push_api
* Push scan results to a GitHub / Gitea repository via REST API.
* Each scanned object becomes a JSON file under /scan/<type>/<key>.json
*
* API spec (GitHub): PUT /repos/{owner}/{repo}/contents/{path}
*   Body: { "message": "...", "content": "<base64>", "sha": "<sha if update>" }
*
* TODO: Implement SHA retrieval for existing files (GET before PUT)
*       to avoid 422 "sha is required" on updates.
*----------------------------------------------------------------------*
FORM push_api.
  DATA: lo_client   TYPE REF TO if_http_client,
        lo_request  TYPE REF TO if_http_request,
        lo_response TYPE REF TO if_http_response,
        lv_url      TYPE string,
        lv_status   TYPE i,
        lv_body     TYPE string,
        lv_encoded  TYPE string,
        ls_scan     TYPE ty_scan_row.

  " Build the base URL from config
  " Expected format: https://api.github.com/repos/<owner>/<repo>
  " or https://<gitea-host>/api/v1/repos/<owner>/<repo>
  DATA(lv_base_url) = CONV string( gs_config-git_url ).
  DATA(lv_token)    = CONV string( gs_config-api_token ).

  IF lv_base_url IS INITIAL.
    WRITE: / '  [ERROR] No Git URL configured.'.
    RETURN.
  ENDIF.

  WRITE: / |  Base URL: { lv_base_url }|.
  WRITE: / |  Objects to push: { lines( gt_scan ) }|.

  LOOP AT gt_scan INTO ls_scan.
    " Build file path: scan/<OBJECT_TYPE>/<OBJECT_KEY>.json
    DATA(lv_obj_type_lower) = to_lower( CONV string( ls_scan-object_type ) ).
    DATA(lv_obj_key_safe)   = ls_scan-object_key.
    TRANSLATE lv_obj_key_safe USING '/ '.   " replace / with space then collapse
    CONDENSE lv_obj_key_safe NO-GAPS.
    REPLACE ALL OCCURRENCES OF ` ` IN lv_obj_key_safe WITH `_`.

    DATA(lv_filepath) = |scan/{ lv_obj_type_lower }/{ lv_obj_key_safe }.json|.
    lv_url = |{ lv_base_url }/contents/{ lv_filepath }|.

    " Build JSON payload — using the metadata field (already JSON)
    " For full content, we'd base64-encode source_code here.
    " TODO: Use proper BASE64 encoding via CL_HTTP_UTILITY=>ENCODE_BASE64
    DATA(lv_content_raw) = ls_scan-metadata.
    cl_http_utility=>encode_base64(
      EXPORTING unencoded = lv_content_raw
      RECEIVING encoded   = lv_encoded ).

    lv_body = |\{"message":"scan: update { lv_filepath }",|
           && |"content":"{ lv_encoded }"\}|.

    " Create HTTP client
    cl_http_client=>create_by_url(
      EXPORTING url                = lv_url
      IMPORTING client             = lo_client
      EXCEPTIONS argument_not_found = 1
                plugin_not_active   = 2
                internal_error      = 3
                OTHERS              = 4 ).

    IF sy-subrc <> 0.
      WRITE: / |    [ERROR] Cannot create HTTP client for { lv_url }|.
      CONTINUE.
    ENDIF.

    lo_request = lo_client->request.
    lo_request->set_method( 'PUT' ).
    lo_request->set_header_field( name = 'Authorization'
                                   value = |token { lv_token }| ).
    lo_request->set_header_field( name = 'Content-Type'
                                   value = 'application/json' ).
    lo_request->set_header_field( name = 'Accept'
                                   value = 'application/vnd.github.v3+json' ).
    lo_request->set_cdata( data = lv_body ).

    lo_client->send( ).
    lo_client->receive( ).
    lo_response = lo_client->response.
    lv_status   = lo_response->get_status( ).

    CASE lv_status.
      WHEN 200 OR 201.
        WRITE: / |    [OK]    { ls_scan-object_key }|.
      WHEN 422.
        " File exists — need to include SHA; log and skip for now
        WRITE: / |    [SKIP]  { ls_scan-object_key } (exists, SHA needed for update)|.
        " TODO: GET file first, extract SHA, then retry PUT with "sha" field
      WHEN OTHERS.
        WRITE: / |    [HTTP { lv_status }] { ls_scan-object_key }|.
    ENDCASE.

    lo_client->close( ).
  ENDLOOP.
ENDFORM.

*----------------------------------------------------------------------*
* FORM push_filedrop
* Write scan results as JSON files to an application server path.
* The path is configured in CFG_KEY = 'AL11_PATH'.
* A Linux-side cron job picks them up and pushes to Git.
*----------------------------------------------------------------------*
FORM push_filedrop.
  DATA: lv_path    TYPE string,
        lv_fname   TYPE string,
        lv_content TYPE string,
        ls_scan    TYPE ty_scan_row.

  DATA(lv_base_path) = CONV string( gs_config-al11_path ).

  IF lv_base_path IS INITIAL.
    WRITE: / '  [ERROR] AL11 path not configured.'.
    RETURN.
  ENDIF.

  WRITE: / |  Writing to AL11 path: { lv_base_path }|.

  LOOP AT gt_scan INTO ls_scan.
    DATA(lv_obj_type_lower) = to_lower( CONV string( ls_scan-object_type ) ).
    DATA(lv_safe_key)       = CONV string( ls_scan-object_key ).
    REPLACE ALL OCCURRENCES OF `/` IN lv_safe_key WITH `_`.

    lv_fname   = |{ lv_base_path }/{ lv_obj_type_lower }_{ lv_safe_key }.json|.
    lv_content = ls_scan-metadata.

    " Append source code to the JSON payload (simplified)
    " TODO: Properly encode source_code into the JSON rather than appending raw
    lv_content = lv_content && cl_abap_char_utilities=>newline
                            && ls_scan-source_code.

    OPEN DATASET lv_fname FOR OUTPUT IN TEXT MODE ENCODING UTF-8.
    IF sy-subrc <> 0.
      WRITE: / |    [ERROR] Cannot open { lv_fname } — check AL11 path and permissions|.
      CONTINUE.
    ENDIF.

    TRANSFER lv_content TO lv_fname.
    CLOSE DATASET lv_fname.

    WRITE: / |    [OK] { lv_fname }|.
  ENDLOOP.

  WRITE: / |  Wrote { lines( gt_scan ) } files.|.
ENDFORM.

*----------------------------------------------------------------------*
* FORM push_abapgit
* Stub — abapGit transport not yet implemented.
* abapGit serializes objects in a specific XML format; the approach
* would be to trigger abapGit programmatically via its API class
* (ZCL_ABAPGIT_API / IF_ABAPGIT_API) if installed on the system.
*----------------------------------------------------------------------*
FORM push_abapgit.
  WRITE: / '  [TODO] abapGit transport not yet implemented.'.
  WRITE: / '         Install abapGit and call ZCL_ABAPGIT_API=>push().'.
  WRITE: / '         Scan data is stored in ZDOC_AGENT_SCAN for manual export.'.
ENDFORM.

*----------------------------------------------------------------------*
* FORM dry_run_report
* Print what would be scanned without writing anything.
*----------------------------------------------------------------------*
FORM dry_run_report.
  WRITE: / '=== DRY RUN — no data written ==='.
  WRITE: / SY-ULINE(70).
  WRITE: / |Objects that would be scanned: { lines( gt_scan ) }|.
  WRITE: /.

  LOOP AT gt_scan INTO DATA(ls_scan).
    WRITE: / | { ls_scan-object_type WIDTH = 8 } { ls_scan-object_key }|.
    IF ls_scan-description IS NOT INITIAL.
      WRITE: |    { ls_scan-description }|.
    ENDIF.
  ENDLOOP.

  WRITE: /.
  WRITE: / |Dependencies that would be recorded: { lines( gt_deps ) }|.
  WRITE: /.

  LOOP AT gt_deps INTO DATA(ls_dep).
    WRITE: / | { ls_dep-source_key WIDTH = 25 } --[{ ls_dep-dep_type }]--> { ls_dep-target_key }|.
  ENDLOOP.
ENDFORM.
