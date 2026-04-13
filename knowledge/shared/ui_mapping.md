# SAP UI5 CSS Selector Patterns

## General Navigation Elements

| Element                  | Stable Selector                                      |
|--------------------------|------------------------------------------------------|
| Shell header             | `#shell-header`                                      |
| Side navigation          | `.sapUshellShellHead`                                |
| Primary toolbar          | `.sapMIBar-CTX`                                      |
| Save button (toolbar)    | `[data-sap-ui-type="sap.m.Button"][title="Save"]`    |
| Deploy button            | `[data-sap-ui-type="sap.m.Button"][title="Deploy"]`  |
| Busy overlay             | `.sapUiLocalBusyIndicator`                           |
| Toast / message strip    | `.sapMMsgStrip`                                      |
| Dialog confirm           | `.sapMDialogScrollCont .sapMBtn:last-child`          |

## Datasphere-Specific Selectors

| Element                       | Selector                                             |
|-------------------------------|------------------------------------------------------|
| Space switcher dropdown       | `[id$="spaceSelector"]`                              |
| Object tree panel             | `.sapSuiteUiCommonsNetworkGraphNode`                 |
| SQL console editor area       | `.ace_editor`                                        |
| Column mapping row            | `[data-column-name]`                                 |
| Validation message list       | `.sapMMessageView .sapMListItems`                    |

## Notes on Dynamic IDs
SAP UI5 generates control IDs like `__button12` that change on every render.
Never hardcode these. Prefer `aria-label`, `title`, or `data-sap-*`
attribute selectors which remain stable across sessions.
