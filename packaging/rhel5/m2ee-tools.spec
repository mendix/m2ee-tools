# spec file for m2ee-tools
#

Summary:       Mendix Deployment Tools
Name:          m2ee-tools
Version:       0.3.6.1
Release:       0.rhel5
Packager:      Hans van Kranenburg \<hans.van.kranenburg@mendix.com\>
License:       BSD
Group:         Misc
URL:           http://www.mendix.com
Source0:       %{name}-%{version}.tar.gz
BuildRoot:     %{_tmppath}/%{name}-%{version}-%{release}-root
BuildRequires: python
BuildArch:     noarch

Patch0: %{name}-private_module.patch

Requires: PyYAML
Requires: python-httplib2
Requires: python-simplejson
Requires: unzip
Requires: sqlite >= 3

%description
The m2ee tools provide an interactive way to manage Mendix Business Server
processes. Using the scripts, a Mendix application can be started, stopped
and monitored.

When using a PostgreSQL database as datastore for the application, m2ee
also provides functionality to dump and restore databases, if the
postgresql-client package is installed.

%prep
 
%setup
%patch0 -p1

%build

%install
%{__mkdir_p} $RPM_BUILD_ROOT%{_bindir}
install -p -m755 src/m2ee.py $RPM_BUILD_ROOT%{_bindir}/m2ee
%{__mkdir_p} $RPM_BUILD_ROOT/usr/share/%{name}/m2ee
python -c "import compileall; compileall.compile_dir('src/m2ee/')"
install src/m2ee/*.py* $RPM_BUILD_ROOT/usr/share/%{name}/m2ee

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%doc CHANGES README LICENSE examples
/usr/bin
/usr/share/%{name}


