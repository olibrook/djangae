import logging
import os
import sys

from django.conf import settings


def setup_datastore_stubs():
    if "test" in sys.argv:
        return

    from google.appengine.datastore import datastore_sqlite_stub
    from google.appengine.api import apiproxy_stub_map
    from google.appengine.datastore import datastore_stub_util

    app_id = application_id()

    datastore = datastore_sqlite_stub.DatastoreSqliteStub(
        "dev~" + app_id,
        os.path.join(data_root(), "datastore.db"),
        require_indexes=False,
        trusted=False,
        root_path=find_project_root(),
        use_atexit=True
    )

    datastore.SetConsistencyPolicy(
          datastore_stub_util.TimeBasedHRConsistencyPolicy()
    )

    apiproxy_stub_map.apiproxy.ReplaceStub(
        'datastore_v3', datastore
    )

def find_project_root():
    """Traverse the filesystem upwards and return the directory containing app.yaml"""
    path = os.path.dirname(os.path.abspath(__file__))

    while True:
        if os.path.exists(os.path.join(path, "app.yaml")):
            return path
        else:
            parent = os.path.dirname(path)
            if parent == path:  # Filesystem root
                break
            else:
                path = parent

    raise RuntimeError("Unable to locate app.yaml")

def data_root():
    path = os.path.join(find_project_root(), ".gaedata")
    if not os.path.exists(path):
        os.makedirs(path)
    return path

def application_id():
    setup_paths()
    from google.appengine.api import app_identity

    try:
        result = app_identity.get_application_id()
    except AttributeError:
        result = None

    if not result:
        #Apparently we aren't running live, probably inside a management command
        from google.appengine.api import appinfo

        info = appinfo.LoadSingleAppInfo(open(os.path.join(find_project_root(), "app.yaml")))

        result = "dev~" + info.application
        os.environ['APPLICATION_ID'] = result
        result = app_identity.get_application_id()

    return result

def possible_sdk_locations():
    POSSIBLE_SDK_LOCATIONS = [
        os.path.join(find_project_root(), "google_appengine"),
        os.path.join(os.path.expanduser("~"), "google_appengine"),
        os.environ.get("APP_ENGINE_SDK"),
        "/usr/local/google_appengine",
        "/Applications/GoogleAppEngineLauncher.app/Contents/Resources/GoogleAppEngine-default.bundle/Contents/Resources/google_appengine",
    ]

    for path in os.environ.get('PATH', '').split(os.pathsep):
        path = path.rstrip(os.sep)
        if path.endswith('google_appengine'):
            POSSIBLE_SDK_LOCATIONS.append(path)
    if os.name in ('nt', 'dos'):
        path = r'%(PROGRAMFILES)s\Google\google_appengine' % os.environ
        POSSIBLE_SDK_LOCATIONS.append(path)

    return [ os.path.realpath(x) for x in POSSIBLE_SDK_LOCATIONS if x ]

def appengine_on_path():
    try:
        from google.appengine.api import apiproxy_stub_map
        apiproxy_stub_map #Silence pylint
        return True
    except ImportError:
        return False

def setup_built_in_library_paths():
    from dev_appserver import fix_sys_path
    fix_sys_path()

    from google.appengine.api import appinfo

    info = appinfo.LoadSingleAppInfo(open(os.path.join(find_project_root(), "app.yaml")))

    try:
        version_from_app_yaml = [ x.version for x in info.libraries if x.name == 'django' ][0]
    except IndexError:
        version_from_app_yaml = 'latest'

    latest_non_deprecated = appinfo._NAME_TO_SUPPORTED_LIBRARY['django'].non_deprecated_versions[-1]
    django_version = float(latest_non_deprecated if version_from_app_yaml == 'latest' else version_from_app_yaml)

    if django_version < 1.5:
        raise RuntimeError("Djangae only supports Django 1.5+")

    #Remove default django
    sys.path = [ x for x in sys.path if "django-1.4" not in x ]

    django_folder = "django-" + str(django_version)
    sys.path.insert(1, os.path.join(os.environ['APP_ENGINE_SDK'], "lib", django_folder))

def setup_additional_libs_path():
    project_root = find_project_root()

    ADDITIONAL_FOLDERS = [ "lib", "libs", "libraries" ]

    for folder in ADDITIONAL_FOLDERS:
        path = os.path.join(project_root, folder)
        if os.path.exists(path) and path not in sys.path:
            sys.path.insert(1, path)

def on_production():
    return 'SERVER_SOFTWARE' in os.environ and not os.environ['SERVER_SOFTWARE'].startswith("Development")


def datastore_available():
    from google.appengine.api import apiproxy_stub_map
    return bool(apiproxy_stub_map.apiproxy.GetStub('datastore_v3'))

def in_testing():
    return "test" in sys.argv

def monkey_patch_unsupported_tests():
    if "DJANGAE_TESTS_SKIPPED" in os.environ:
        return

    unsupported_tests = []

    if 'django.contrib.auth' in settings.INSTALLED_APPS:
        unsupported_tests.extend([
            #These auth tests override the AUTH_USER_MODEL setting, which then uses M2M joins
            'django.contrib.auth.tests.auth_backends.CustomPermissionsUserModelBackendTest.test_custom_perms',
            'django.contrib.auth.tests.auth_backends.CustomPermissionsUserModelBackendTest.test_get_all_superuser_permissions',
            'django.contrib.auth.tests.auth_backends.CustomPermissionsUserModelBackendTest.test_has_no_object_perm',
            'django.contrib.auth.tests.auth_backends.CustomPermissionsUserModelBackendTest.test_has_perm',
            'django.contrib.auth.tests.auth_backends.ExtensionUserModelBackendTest.test_custom_perms',
            'django.contrib.auth.tests.auth_backends.ExtensionUserModelBackendTest.test_has_perm',
            'django.contrib.auth.tests.auth_backends.ExtensionUserModelBackendTest.test_get_all_superuser_permissions',
            'django.contrib.auth.tests.auth_backends.ExtensionUserModelBackendTest.test_has_no_object_perm'
        ])

    from unittest import skip

    for test in unsupported_tests:
        module_path, klass_name, method_name = test.rsplit(".", 2)
        __import__(module_path, klass_name)

        module = sys.modules[module_path]
        if hasattr(module, klass_name):
            klass = getattr(module, klass_name)
            method = getattr(klass, method_name)
            setattr(klass, method_name, skip("Not supported by Djangae")(method))

    os.environ["DJANGAE_TESTS_SKIPPED"] = "1"

def setup_paths():
    if not appengine_on_path():
        for k in [k for k in sys.modules if k.startswith('google')]:
            del sys.modules[k]

        for path in possible_sdk_locations():
            if os.path.exists(path):
                os.environ['APP_ENGINE_SDK'] = path
                sys.path.insert(1, path)
                logging.info("Using App Engine SDK at '%s'", path)
                break
        else:
            logging.error("Unable to locate the App Engine SDK")
            sys.exit(1)

        #Configure App Engine's built in libraries
        setup_built_in_library_paths()

    setup_additional_libs_path() #Add any folders in the project root that may contain extra libraries

    if in_testing():
        monkey_patch_unsupported_tests()
