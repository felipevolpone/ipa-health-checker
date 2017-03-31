
import csv, argparse, sys, os
from .utils import get_logger, execute, create_logger, get_file_full_path
from . import checker_helper as helper
from . import settings


class HealthChecker(object):

    def __init__(self, sys_args=None):
        self.sys_args = sys_args if sys_args else sys.argv[1:]
        self.logger = get_logger()

        self.parser = argparse.ArgumentParser(description="IPA Health Checker")

        subparsers = self.parser.add_subparsers(dest='command')

        list_nssdb = subparsers.add_parser('list_certs')
        list_nssdb.add_argument('path')

        certs_valid = subparsers.add_parser('certs_expired')
        certs_valid.add_argument('path')

        ck_path_certs = subparsers.add_parser('ck_path_and_flags')
        ck_path_certs.add_argument('--csv_file', help='CSV file with info of path and name \
of the certs. Check the docs for more info')

        ck_kra = subparsers.add_parser('ck_kra_setup')
        ck_kra.add_argument('--dir', help='Where the kra dir should be found',
                            default=settings.KRA_DEFAULT_DIR_PATH)
        ck_kra.add_argument('--cert', help='Where the kra cert should be found',
                            default=settings.KRA_DEFAULT_CERT_PATH)

        self.parsed_args = self.parser.parse_args(self.sys_args)

    def run_cli(self):
        args = self.parser.parse_args(self.sys_args)
        if not hasattr(self, args.command):
            self.logger.error('command not found')
            return

        getattr(self, args.command)()

    def list_certs(self, path=None):
        """
        Method to list the certificates in a given path.

        Returns:
            A list of tuples where which tuple has the name of the
            certificate and its properties.

            eg: [('subsystemCert cert-pki-ca', 'u,u,u')]
        """

        path = path if path else self.parsed_args.path
        command = 'certutil -d {} -L'
        command = command.format(path)

        self.logger.debug('Running command: $ {}'.format(command))

        cert_list = self._execute_and_get_certs(command)

        self.logger.debug('Certificates found: {}'.format(cert_list))

        return cert_list

    def _execute_and_get_certs(self, command):
        certs = execute(command)

        cert_list = []
        for cert in certs:
            extracted = helper.extract_cert_name(cert)
            if extracted:
                cert_list.append(extracted)

        return cert_list

    def _get_cert(self, path, cert_name):
        command = 'certutil -d {} -L -n \"{}\"'
        command = command.format(path, cert_name)

        self.logger.debug('Running command: $ {}'.format(command))

        return execute(command)

    def certs_expired(self):
        """
        Method to check if the certificates in a given path
        expired  (if they expiration date are valid).

        Returns:
            A list of tuples where which tuple has the name of the
            certificate and its status.

            eg: [('subsystemCert cert-pki-ca', True),
                 ('Server-Cert cert-pki-ca', False)]
        """

        cert_list = self.list_certs()

        certs_status = []

        for cert_name, _ in cert_list:
            cert_details = self._get_cert(self.parsed_args.path, cert_name)
            is_valid = helper.compare_cert_date(cert_details)

            certs_status.append((cert_name, is_valid))

            self.logger.info('Certificate \"{}\" is expired: {}'.format(
                cert_name, not is_valid))

        return certs_status

    def ck_path_and_flags(self):
        """
        Method to check if the certificates listed on file certs_list.csv
        exists where they should exist and if they have the right trust flags.

        Returns: True or False
        """

        full_path = None
        if self.parsed_args.csv_file:
            full_path = self.parsed_args.csv_file
        else:
            full_path = get_file_full_path(settings.CERTS_LIST_FILE)

        certmonger_data = None

        with open(full_path) as f:

            certs_from_path, old_path = None, None

            for row in csv.DictReader(f, delimiter=';'):

                if row['path'] != old_path:
                    certs_from_path = self.list_certs(row['path'])

                certs_names = [cert[0] for cert in certs_from_path]

                if row['name'] not in certs_names:
                    helper.treat_cert_not_found(self.logger, row)
                    return False

                cert_index = certs_names.index(row['name'])
                cert_flags = certs_from_path[cert_index][1]

                if row['flags'] != cert_flags:
                    helper.treat_cert_with_wrong_flags(self.logger, row, cert_flags)
                    return False

                if row['certmonger'] == 'True':
                    if certmonger_data is None:
                        certmonger_data = helper.certmonger_list()

                    is_monitoring = False
                    for cert in certmonger_data:
                        if row['name'] in cert['certificate']:
                            is_monitoring = True
                            break

                    if not is_monitoring:
                        # add log message
                        return False

                old_path = row['path']

        self.logger.info('Certificates checked successfully.')
        return True

    def ck_kra_setup(self):
        path_to_kra = self.parsed_args.dir

        result = {'kra_in_expected_path': False, 'kra_cert_present': False}

        if os.path.exists(path_to_kra) and os.path.isdir(path_to_kra):
            result['kra_in_expected_path'] = True

        certs_from_path = self.list_certs(self.parsed_args.cert)
        certs_names = [cert[0] for cert in certs_from_path]

        kra_certs = filter(lambda cert: 'kra' in cert.lower(), certs_names)

        if any(kra_certs):
            result['kra_cert_present'] = True

        message = 'KRA is installed: {installed}. Cert was found: {cert_found}'
        message = message.format(installed=result['kra_in_expected_path'],
                                 cert_found=result['kra_cert_present'])

        self.logger.info(message)

        return result


if __name__ == '__main__':
    create_logger()
    HealthChecker().run_cli()