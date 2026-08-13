class ListingTemplateNotFoundError(Exception):
    """No listing_template row for the job's category × marketplace."""


class ListingFillError(Exception):
    """Listing fill failed for a reason other than missing template/job."""


class DropboxError(Exception):
    """Dropbox upload or shared-link creation failed."""
