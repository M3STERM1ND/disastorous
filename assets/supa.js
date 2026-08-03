// Shared Supabase client. The publishable/anon key below is meant to be public —
// it has no privileges on its own; access is controlled by the Row Level Security
// policies on the project (see supabase_setup.sql). Never put the service_role
// key here or anywhere else client-side.
window.SUPA_URL = "https://ywewsehjgciebpvkukyh.supabase.co";
window.SUPA_ANON_KEY = "sb_publishable_19F357jgF1gJUu-Dpm_5JQ_3kmi0KVy";
window.supa = supabase.createClient(window.SUPA_URL, window.SUPA_ANON_KEY);
