# Evaluation report

Portal A (synthetic, from the trace) and mock Portal B (a deliberately different portal, `portal_b/`), as-of date 2026-11-02. Total wall time 468s.

**Cases: 77/77 passed. Repeatability: 11/11 passed (11 with identical results, 11 with identical action logs).**

| # | Case | Portal | Group | Scenarios | Expected | Got | Pass | s |
|---|---|---|---|---|---|---|---|---|
| 1 | trace_replay_fidelity | A | fidelity | none | trace's own selectors reach the request page | NDC 12341111111 -> No Results | options for 'Simponi Aria': 1 | state row after ZIP: Oklahoma | landed on: Test Test (Key: 4P36HRN2) | yes | 4.5 |
| 2 | P001_trace_exact | A | sample | (defaults) | SUCCESS | SUCCESS | yes | 20.4 |
| 3 | P002_clean_male_other_bin | A | sample | (defaults) | SUCCESS | SUCCESS | yes | 21.0 |
| 4 | P003_clean_hyphen_name | A | sample | (defaults) | SUCCESS | SUCCESS | yes | 20.0 |
| 5 | P004_bad_dob_and_zip | A | sample | (defaults) | ESCALATED / date_of_birth | ESCALATED / date_of_birth | yes | 0.1 |
| 6 | P005_missing_sex_bad_bin | A | sample | (defaults) | ESCALATED / sex | ESCALATED / sex | yes | 0.1 |
| 7 | clean_no_popups | A | clean | none | SUCCESS | SUCCESS | yes | 18.7 |
| 8 | clean_all_popups | A | popup | chat_widget,announcement,bottom_banner,session_warning,survey_overlay | SUCCESS | SUCCESS | yes | 22.1 |
| 9 | login_maintenance_notice | A | popup | maintenance_notice,chat_widget | SUCCESS | SUCCESS | yes | 20.5 |
| 10 | popup_appears_mid_form | A | popup | session_warning_late,chat_widget | SUCCESS | SUCCESS | yes | 20.5 |
| 11 | slow_drug_and_form_search | A | edge | slow_drug_search,slow_forms | SUCCESS | SUCCESS | yes | 23.2 |
| 12 | random_element_ids | A | edge | random_ids | SUCCESS | SUCCESS | yes | 18.7 |
| 13 | native_date_picker | A | edge | native_dates | SUCCESS | SUCCESS | yes | 18.5 |
| 14 | custom_state_dropdown | A | edge | state_not_prefilled | SUCCESS | SUCCESS | yes | 19.4 |
| 15 | flaky_start_retry | A | edge | flaky_start | SUCCESS | SUCCESS | yes | 20.7 |
| 16 | session_expiry_relogin | A | edge | session_expiry | SUCCESS | SUCCESS | yes | 28.7 |
| 17 | kitchen_sink | A | edge | chat_widget,announcement,bottom_banner,session_warning,survey_overlay,maintenance_notice,slow_drug_search,slow_forms,random_ids,native_dates,state_not_prefilled,flaky_start,session_expiry | SUCCESS | SUCCESS | yes | 43.8 |
| 18 | medication_by_ndc | A | clean | (defaults) | SUCCESS | SUCCESS | yes | 20.3 |
| 19 | start_request_fails | A | edge | start_fails | FAILED | FAILED | yes | 18.5 |
| 20 | duplicate_patient_dialog | A | edge | duplicate_patient | ESCALATED / patient | ESCALATED / patient | yes | 10.6 |
| 21 | no_forms_found | A | edge | no_forms | ESCALATED / form | ESCALATED / form | yes | 14.3 |
| 22 | form_policy_clarify | A | edge | (defaults) | ESCALATED / form | ESCALATED / form | yes | 17.3 |
| 23 | ambiguous_medication | A | portal_reject | (defaults) | ESCALATED / medication_search | ESCALATED / medication_search | yes | 3.4 |
| 24 | unknown_medication | A | portal_reject | (defaults) | ESCALATED / medication_search | ESCALATED / medication_search | yes | 3.4 |
| 25 | unknown_ndc | A | portal_reject | (defaults) | ESCALATED / medication_search | ESCALATED / medication_search | yes | 3.4 |
| 26 | missing_medication | A | validation | (defaults) | ESCALATED / medication_search | ESCALATED / medication_search | yes | 0.1 |
| 27 | ndc_wrong_length | A | validation | (defaults) | ESCALATED / medication_search | ESCALATED / medication_search | yes | 0.1 |
| 28 | name_with_symbols | A | validation | (defaults) | ESCALATED / first_name | ESCALATED / first_name | yes | 0.1 |
| 29 | name_trailing_space | A | validation | (defaults) | ESCALATED / last_name | ESCALATED / last_name | yes | 0.1 |
| 30 | sex_lowercase | A | validation | (defaults) | ESCALATED / sex | ESCALATED / sex | yes | 0.1 |
| 31 | dob_iso_format | A | validation | (defaults) | ESCALATED / date_of_birth | ESCALATED / date_of_birth | yes | 0.1 |
| 32 | dob_in_future | A | validation | (defaults) | ESCALATED / date_of_birth | ESCALATED / date_of_birth | yes | 0.1 |
| 33 | dob_age_over_120 | A | validation | (defaults) | ESCALATED / date_of_birth | ESCALATED / date_of_birth | yes | 0.1 |
| 34 | dob_impossible_date | A | validation | (defaults) | ESCALATED / date_of_birth | ESCALATED / date_of_birth | yes | 0.1 |
| 35 | zip_plus_four | A | validation | (defaults) | ESCALATED / patient_zip | ESCALATED / patient_zip | yes | 0.1 |
| 36 | state_full_name | A | validation | (defaults) | ESCALATED / insurance_state | ESCALATED / insurance_state | yes | 0.1 |
| 37 | state_lowercase | A | validation | (defaults) | ESCALATED / insurance_state | ESCALATED / insurance_state | yes | 0.1 |
| 38 | bin_with_letters | A | validation | (defaults) | ESCALATED / rx_bin | ESCALATED / rx_bin | yes | 0.1 |
| 39 | bin_as_json_number | A | validation | (defaults) | ESCALATED / rx_bin | ESCALATED / rx_bin | yes | 0.1 |
| 40 | pcn_bad_chars | A | validation | (defaults) | ESCALATED / rx_pcn | ESCALATED / rx_pcn | yes | 0.1 |
| 41 | group_with_space | A | validation | (defaults) | ESCALATED / rx_group | ESCALATED / rx_group | yes | 0.1 |
| 42 | payer_eligibility_offer | A | edge | payer_eligibility,chat_widget | SUCCESS | SUCCESS | yes | 22.4 |
| 43 | therapeutic_alternatives_keep_drug | A | edge | therapeutic_alternatives,chat_widget | SUCCESS | SUCCESS | yes | 23.6 |
| 44 | existing_pa_active | A | edge | existing_pa,chat_widget | ESCALATED / patient | ESCALATED / patient | yes | 18.5 |
| 45 | existing_pa_expired | A | edge | existing_pa_expired,chat_widget | SUCCESS | SUCCESS | yes | 20.0 |
| 46 | lamar_post_start_states | A | edge | payer_eligibility,therapeutic_alternatives,existing_pa_expired,chat_widget,random_ids | SUCCESS | SUCCESS | yes | 25.6 |
| 47 | request_page_load_error_reload | A | edge | request_page_error,chat_widget | SUCCESS | SUCCESS | yes | 21.4 |
| 48 | native_confirm_dialog | A | edge | native_confirm,chat_widget | ESCALATED / portal | ESCALATED / portal | yes | 18.4 |
| 49 | skip_forms_for_other_states | A | edge | other_state_forms_first,chat_widget | SUCCESS | SUCCESS | yes | 20.3 |
| 50 | review_page_then_submit | A | edge | review_step,chat_widget | SUCCESS | SUCCESS | yes | 24.6 |
| 51 | review_page_late_validation | A | edge | review_step,review_validation,chat_widget | ESCALATED / patient_zip | ESCALATED / patient_zip | yes | 24.2 |
| 52 | review_page_flaky_submit | A | edge | review_step,flaky_start,chat_widget | SUCCESS | SUCCESS | yes | 28.1 |
| 53 | medical_bad_npi_luhn | A | validation (brief Section 4 shape) | (defaults) | ESCALATED / provider_npi | ESCALATED / provider_npi | yes | 0.1 |
| 54 | medical_member_id_format | A | validation (brief Section 4 shape) | (defaults) | ESCALATED / member_id | ESCALATED / member_id | yes | 0.1 |
| 55 | medical_service_date_past | A | validation (brief Section 4 shape) | (defaults) | ESCALATED / service_date | ESCALATED / service_date | yes | 0.1 |
| 56 | medical_service_date_too_far | A | validation (brief Section 4 shape) | (defaults) | ESCALATED / service_date | ESCALATED / service_date | yes | 0.1 |
| 57 | medical_icd10_format | A | validation (brief Section 4 shape) | (defaults) | ESCALATED / icd10_code | ESCALATED / icd10_code | yes | 0.1 |
| 58 | medical_cpt_not_5_digits | A | validation (brief Section 4 shape) | (defaults) | ESCALATED / cpt_code | ESCALATED / cpt_code | yes | 0.1 |
| 59 | medical_child_without_subscriber | A | validation (brief Section 4 shape) | (defaults) | ESCALATED / subscriber_name | ESCALATED / subscriber_name | yes | 0.1 |
| 60 | medical_urgency_unknown | A | validation (brief Section 4 shape) | (defaults) | ESCALATED / urgency | ESCALATED / urgency | yes | 0.1 |
| 61 | medical_missing_payer | A | validation (brief Section 4 shape) | (defaults) | ESCALATED / payer_name | ESCALATED / payer_name | yes | 0.1 |
| 62 | B_P001_trace_exact | B | portal_b sample | (defaults) | SUCCESS | SUCCESS | yes | 22.6 |
| 63 | B_P002_clean_male_other_bin | B | portal_b sample | (defaults) | SUCCESS | SUCCESS | yes | 23.1 |
| 64 | B_P003_clean_hyphen_name | B | portal_b sample | (defaults) | SUCCESS | SUCCESS | yes | 22.2 |
| 65 | B_P004_bad_dob_and_zip | B | portal_b sample | (defaults) | ESCALATED / date_of_birth | ESCALATED / date_of_birth | yes | 0.1 |
| 66 | B_P005_missing_sex_bad_bin | B | portal_b sample | (defaults) | ESCALATED / sex | ESCALATED / sex | yes | 0.1 |
| 67 | B_all_popups_slow_lookup | B | portal_b popup | cookie_banner,idle_modal,feedback_modal,slow_lookup | SUCCESS | SUCCESS | yes | 25.1 |
| 68 | B_sex_x_unknown_other | B | portal_b clean | (defaults) | SUCCESS | SUCCESS | yes | 22.7 |
| 69 | B_portal_rejects_bin | B | portal_b edge | unknown_plan | ESCALATED / rx_bin | ESCALATED / rx_bin | yes | 12.5 |
| 70 | B_attestation_required | B | portal_b edge | attestation | ESCALATED / portal | ESCALATED / portal | yes | 17.6 |
| 71 | B_duplicate_request_dialog | B | portal_b edge | duplicate_request | ESCALATED / patient | ESCALATED / patient | yes | 16.6 |
| 72 | B_ambiguous_medication | B | portal_b edge | (defaults) | ESCALATED / medication_search | ESCALATED / medication_search | yes | 15.1 |
| 73 | B_plan_rejects_submit | B | portal_b edge | plan_rejects | FAILED | FAILED | yes | 19.6 |
| 74 | name_internal_spaces | A | valid boundary | (defaults) | SUCCESS | SUCCESS | yes | 20.3 |
| 75 | B_name_internal_spaces | B | valid boundary | (defaults) | SUCCESS | SUCCESS | yes | 22.6 |
| 76 | rerun_after_success_no_double_submit | A | ledger | (defaults) | SUCCESS, same request key, 0 new requests | SUCCESS 4P36HRN2, 0 new requests | yes | 0.1 |
| 77 | interrupted_after_submit_escalates | A | ledger | (defaults) | ESCALATED / submission, 0 new requests | ESCALATED / submission, 0 new requests | yes | 0.1 |

## Repeatability

Each case run independently N times (fresh ledger each run). Result JSON and action log must be byte-identical.

| Case | Runs | Status | Identical results | Identical action logs | Log lines | Pass | Note |
|---|---|---|---|---|---|---|---|
| P001_trace_exact | 3 | SUCCESS | True | True | 24 | yes |  |
| P002_clean_male_other_bin | 3 | SUCCESS | True | True | 25 | yes |  |
| clean_all_popups | 3 | SUCCESS | True | True | 30 | yes |  |
| kitchen_sink | 3 | SUCCESS | True | True | 48 | yes |  |
| flaky_start_retry | 3 | SUCCESS | True | True | 24 | yes |  |
| duplicate_patient_dialog | 3 | ESCALATED | True | True | 15 | yes |  |
| popup_appears_mid_form | 3 | SUCCESS | True | True | 25 | yes |  |
| B_P001_trace_exact | 3 | SUCCESS | True | True | 30 | yes |  |
| B_all_popups_slow_lookup | 3 | SUCCESS | True | True | 32 | yes |  |
| review_page_then_submit | 3 | SUCCESS | True | True | 27 | yes |  |
| lamar_post_start_states | 3 | SUCCESS | True | True | 28 | yes |  |

## Notes

- **P001_trace_exact**: ; saved values verified
- **P002_clean_male_other_bin**: ; saved values verified
- **P003_clean_hyphen_name**: ; saved values verified
- **clean_no_popups**: ; saved values verified
- **clean_all_popups**: ; saved values verified
- **login_maintenance_notice**: ; saved values verified
- **popup_appears_mid_form**: ; saved values verified
- **slow_drug_and_form_search**: ; saved values verified
- **random_element_ids**: ; saved values verified
- **native_date_picker**: ; saved values verified
- **custom_state_dropdown**: ; saved values verified
- **flaky_start_retry**: ; saved values verified
- **session_expiry_relogin**: ; saved values verified
- **kitchen_sink**: ; saved values verified
- **medication_by_ndc**: ; saved values verified
- **payer_eligibility_offer**: ; saved values verified
- **therapeutic_alternatives_keep_drug**: ; saved values verified
- **existing_pa_expired**: ; saved values verified
- **lamar_post_start_states**: ; saved values verified
- **request_page_load_error_reload**: ; saved values verified
- **skip_forms_for_other_states**: ; saved values verified
- **review_page_then_submit**: ; saved values verified
- **review_page_late_validation**: The review page rejects a valid-looking ZIP only on Submit; nothing is created and the agent escalates the field.
- **review_page_flaky_submit**: ; saved values verified
- **B_P001_trace_exact**: ; saved values verified
- **B_P002_clean_male_other_bin**: ; saved values verified
- **B_P003_clean_hyphen_name**: ; saved values verified
- **B_all_popups_slow_lookup**: ; saved values verified
- **B_sex_x_unknown_other**: ; saved values verified
- **name_internal_spaces**: ; saved values verified
- **B_name_internal_spaces**: ; saved values verified

## Reasons returned

- **trace_replay_fidelity**:
- **P001_trace_exact**: Prior authorization request created; the portal returned its reference number.
- **P002_clean_male_other_bin**: Prior authorization request created; the portal returned its reference number.
- **P003_clean_hyphen_name**: Prior authorization request created; the portal returned its reference number.
- **P004_bad_dob_and_zip**: Record failed validation: date of birth '1986-13-11' is not a valid MM/DD/YYYY date (+1 more)
- **P005_missing_sex_bad_bin**: Record failed validation: sex is missing (+1 more)
- **clean_no_popups**: Prior authorization request created; the portal returned its reference number.
- **clean_all_popups**: Prior authorization request created; the portal returned its reference number.
- **login_maintenance_notice**: Prior authorization request created; the portal returned its reference number.
- **popup_appears_mid_form**: Prior authorization request created; the portal returned its reference number.
- **slow_drug_and_form_search**: Prior authorization request created; the portal returned its reference number.
- **random_element_ids**: Prior authorization request created; the portal returned its reference number.
- **native_date_picker**: Prior authorization request created; the portal returned its reference number.
- **custom_state_dropdown**: Prior authorization request created; the portal returned its reference number.
- **flaky_start_retry**: Prior authorization request created; the portal returned its reference number.
- **session_expiry_relogin**: Prior authorization request created; the portal returned its reference number.
- **kitchen_sink**: Prior authorization request created; the portal returned its reference number.
- **medication_by_ndc**: Prior authorization request created; the portal returned its reference number.
- **start_request_fails**: Navitus Health Solutions Commercial Exception to Coverage Request Form does not accept electronic prior authorization for this member. Fax the completed form to the plan instead.
- **duplicate_patient_dialog**: The portal reports a possible duplicate patient or an existing open request. Dialog: 'Possible existing patient'
- **no_forms_found**: The portal found no forms for this medication and insurance.
- **form_policy_clarify**: The portal offered 3 forms: Navitus Health Solutions Commercial Exception to Coverage Request Form; Moda Health Commercial and Marketplace Prior Authorization Request Form; Navitus Health Solutions Medicare Exception to Coverage Request Form
- **ambiguous_medication**: 'Humira' matches several entries in 'Search for medication name or NDC number': Humira Pen 40MG/0.4ML pen-injector kit; Humira 40MG/0.8ML prefilled syringe kit; Humira Pen-CD/UC/HS Starter 80MG/0.8ML kit
- **unknown_medication**: The portal has no 'Search for medication name or NDC number' entry for 'Notarealdrug'.
- **unknown_ndc**: The portal has no 'Search for medication name or NDC number' entry for '12341111111'.
- **missing_medication**: Record failed validation: medication_search is missing
- **ndc_wrong_length**: Record failed validation: '578940350' looks like an NDC but is not 10 or 11 digits
- **name_with_symbols**: Record failed validation: patient first name 'T3st' contains characters other than letters, spaces, hyphens or apostrophes
- **name_trailing_space**: Record failed validation: last_name has leading or trailing spaces
- **sex_lowercase**: Record failed validation: sex 'f' is not one of M, F, X
- **dob_iso_format**: Record failed validation: date of birth '1986-11-13' is not a valid MM/DD/YYYY date
- **dob_in_future**: Record failed validation: date of birth 01/01/2027 is in the future
- **dob_age_over_120**: Record failed validation: date of birth 01/01/1900 gives an age over 120
- **dob_impossible_date**: Record failed validation: date of birth '02/30/1986' is not a valid MM/DD/YYYY date
- **zip_plus_four**: Record failed validation: ZIP code '74055-1234' is not 5 digits
- **state_full_name**: Record failed validation: insurance state 'Oklahoma' is not a 2-letter US state code (e.g. OK)
- **state_lowercase**: Record failed validation: insurance state 'ok' is not a 2-letter US state code (e.g. OK)
- **bin_with_letters**: Record failed validation: RxBIN '61O602' is neither six digits nor a captured supported identifier.
- **bin_as_json_number**: Record failed validation: rx_bin should be text, got int (610602)
- **pcn_bad_chars**: Record failed validation: RxPCN 'NV-T' may only contain letters and digits (max 10)
- **group_with_space**: Record failed validation: RxGroup 'GRP 4421' may only contain letters, digits and hyphens (max 15)
- **payer_eligibility_offer**: Prior authorization request created; the portal returned its reference number.
- **therapeutic_alternatives_keep_drug**: Prior authorization request created; the portal returned its reference number.
- **existing_pa_active**: The portal shows an existing PA for this patient and medication (key B7QK2M4X, status: sent to plan).
- **existing_pa_expired**: Prior authorization request created; the portal returned its reference number.
- **lamar_post_start_states**: Prior authorization request created; the portal returned its reference number.
- **request_page_load_error_reload**: Prior authorization request created; the portal returned its reference number.
- **native_confirm_dialog**: The portal asked for a confirmation the agent will not give: 'Start a new prior authorization request for Test Test?'. It was dismissed.
- **skip_forms_for_other_states**: Prior authorization request created; the portal returned its reference number.
- **review_page_then_submit**: Prior authorization request created; the portal returned its reference number.
- **review_page_late_validation**: Portal rejected 'Patient Zip Code' when starting the request: ZIP code 74055 is outside the service area of the selected plan.
- **review_page_flaky_submit**: Prior authorization request created; the portal returned its reference number.
- **medical_bad_npi_luhn**: Record failed validation: provider NPI '1003000127' fails the NPI check digit (Luhn)
- **medical_member_id_format**: Record failed validation: member ID '123456789' is not 1 letter followed by 9 digits
- **medical_service_date_past**: Record failed validation: service date 2026-10-01 is in the past
- **medical_service_date_too_far**: Record failed validation: service date 2027-06-01 is more than 180 days ahead
- **medical_icd10_format**: Record failed validation: ICD-10 code '54.50' is not a valid ICD-10 format (e.g. M54.50)
- **medical_cpt_not_5_digits**: Record failed validation: CPT code '9711' is not 5 digits
- **medical_child_without_subscriber**: Record failed validation: subscriber relationship is 'child' but the subscriber's name is missing (+1 more)
- **medical_urgency_unknown**: Record failed validation: urgency 'urgent' is not one of standard, expedited
- **medical_missing_payer**: Record failed validation: payer_name is missing
- **B_P001_trace_exact**: Prior authorization request created; the portal returned its reference number.
- **B_P002_clean_male_other_bin**: Prior authorization request created; the portal returned its reference number.
- **B_P003_clean_hyphen_name**: Prior authorization request created; the portal returned its reference number.
- **B_P004_bad_dob_and_zip**: Record failed validation: date of birth '1986-13-11' is not a valid MM/DD/YYYY date (+1 more)
- **B_P005_missing_sex_bad_bin**: Record failed validation: sex is missing (+1 more)
- **B_all_popups_slow_lookup**: Prior authorization request created; the portal returned its reference number.
- **B_sex_x_unknown_other**: Prior authorization request created; the portal returned its reference number.
- **B_portal_rejects_bin**: Portal rejected 'BIN / IIN': No pharmacy plan matches this BIN / IIN.
- **B_attestation_required**: The portal requires fields that are not in the data contract: I attest that this information is accurate and complete
- **B_duplicate_request_dialog**: The portal reports a possible duplicate patient or an existing open request. Dialog: 'Possible duplicate'
- **B_ambiguous_medication**: 'Humira' matches several entries in 'Drug to authorize': Humira 40MG/0.4ML pen; Humira 40MG/0.8ML pen; Humira 80MG/0.8ML pen
- **B_plan_rejects_submit**: The plan does not accept electronic prior authorization for this drug. Fax the plan's paper form instead.
- **name_internal_spaces**: Prior authorization request created; the portal returned its reference number.
- **B_name_internal_spaces**: Prior authorization request created; the portal returned its reference number.
- **rerun_after_success_no_double_submit**: Prior authorization request created; the portal returned its reference number.
- **interrupted_after_submit_escalates**: A previous run was interrupted after starting the request; it may exist.
