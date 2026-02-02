# %%

# Import required modules
import os

from mmif import Mmif

from typing import List

# %%
# Define functions

def mmif_check ( mmif_path:str , complain:bool=False) -> List[str]:
    """ 
    Returns a list which may include these values
    - 'absent' or 'exists'
    - 'invalid' or 'valid'
    - 'blank' or 'laden'
    - 'error-views'
    """

    statuses = []

    if not os.path.isfile(mmif_path): 
        # MMIF file is absent
        statuses.append('absent')
        if complain:
            print("MMIF file not found at " + mmif_path)
    else:
        statuses.append('exists')

        with open(mmif_path, "r") as file:
            mmif_str = file.read()

        try:
            mmif_obj = Mmif(mmif_str)
        except Exception as e:
            statuses.append('invalid')
            if complain:
                print("Encountered exception:")
                print(e)
                print("MMIF check failed for " + mmif_path)
        else:
            statuses.append('valid')

            if len(mmif_obj.views) == 0:
                statuses.append('blank')
                if complain:
                    print("MMIF file contains no views, " + mmif_path)
            else:
                statuses.append('laden')

                error_views = [ v for v in mmif_obj.views if "error" in v.metadata ]
                if len(error_views) > 0:
                    statuses.append('error-views')
                    if complain:
                        print("MMIF file contains error views, " + mmif_path)
    
    assert len(statuses) > 0
    return statuses



def make_blank_mmif (media_filename:str, mime:str) -> str:
    from mmif.utils.cli import source
    return source.generate_source_mmif_from_file([f"{mime}:{media_filename}"], prefix='/data')
