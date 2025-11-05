#!/bin/bash
# Originally written by Kevin
# Updated by Owen to keep secrets elsewhere

# takes one argument - SONY ID, NOT the ams.assets.asset_id - and returns an xml string for use by the AMS php application
# exits when no arg is given or when fails to authenticate with sony or when media item is not found
# requires data in ./config/ci.yml
# requires write access to /tmp/

if [ "$#" -ne 1 ];
	then echo; #exit;
fi;

# config_file_path=/var/www/html/application/config/ci.yml;
#config_file_path=$(cd $(dirname "$0");pwd -P)/config/copy_ci.yml;
#config_file_path=$(cd $(dirname "$0");pwd -P)/../../../secrets/ci.yml;
config_file_path=$HOME/.clams-kitchen/secrets/ci.yml;



# media_item_id='d9765f36db1f43118c12ed153e9ba565'; ## REMOVE AFTER TESTING
# media_item_id=`echo "$1" | awk '{print $1}'`; ## THIS WAS USED WHEN ARG IN WAS THE SONY ID STRING
# media_item_id=`ssh -i ~/.ssh/amsnew/id_rsa root@ams.americanarchive.org "mysql ams -u amsread --skip-column-names -B -e \"select identifier from identifiers where identifier_source = 'Sony Ci' and assets_id=$1 LIMIT 1\""`;
media_item_id=$1; # feed it sony ids directly



credString=`grep '^cred_string:' "$config_file_path"  | awk '{print $2}'`;
client_id=`grep '^client_id:' "$config_file_path"  | awk '{print $2}'`;
#client_id='badteststring';

client_secret=`grep '^client_secret:' "$config_file_path"  | awk '{print $2}'`;
workspace_id=`grep '^workspace_id:' "$config_file_path"  | awk '{print $2}'`;

access_token_filepath="/tmp/$workspace_id";
touch "$access_token_filepath";
access_token=`cat "$access_token_filepath"`;
refresh_token='';
media_getString='';
media_getResponseCode='';
mediaDataString='';


function initAuth 
{
	curl -s -S -XPOST -i "https://api.cimediacloud.com/oauth2/token" -H "Authorization: Basic $credString" -H "Content-Type: application/x-www-form-urlencoded" -d "grant_type=password&client_id=$client_id&client_secret=$client_secret" ;
}


function renewAuth
{
	curl -s -S -XPOST -i "https://api.cimediacloud.com/oauth2/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=refresh_token&refresh_token=$refresh_token&client_id=$client_id&client_secret=$client_secret" ;
}

function old_getKeyedValue
{
#	 arg1 is bigJSON string, arg2 is keyName string
	foo=`echo "$1" | sed -e 's#^.*{##1' -e 's#}.*$##1' -e 's#{.*}##g'  -e "s#\"$2\"*:#&\
#1" | grep -A1 "\"$2\"*:" | tail -1 | sed -e "s#\"$2\"*:##1" | cut -f1 -d,`;

	fooLength=`echo -en "$foo" | wc -c | awk '{print $1}'`;
	fooFirst=`echo -en "$foo" | cut -c1`;
	fooLast=`echo -en "$foo" | cut -c"$fooLength"`;
	if [ "$fooFirst" == '"' -a "$fooLast" == '"' -a $(echo -en "$foo" | tr -d '"' | wc -c | awk '{print $1}') -eq $(expr "$fooLength" - 2) ];
	then
		echo "$foo" | tr -d '"' ;
	else
		echo "$foo" ;
	fi;
}

function getKeyedValue
{
	#	 arg1 is a JSON string, arg2 is keyName string
	echo "$1" | ./JSON.sh -b | grep "$2" | cut -f2- | sed -e 's#^"##1' -e 's#".*$##1';
	#	strings returned will NOT be quoted
}


function getResponseCode
{
	echo "$1" | head -1 | awk '{print $2}'
}

function getHTTPBody
{
	
	firstEmptyLineNum=`echo "$1" | grep -vn '[[:alnum:]]' | head -1 | awk -F: '{print $1}'`;
	if [ "$firstEmptyLineNum" ];
	then
		echo "$1" | tail -$(expr $(echo "$1" | wc -l | awk '{print $1}') - "$firstEmptyLineNum" );
	else
		echo -en '';
	fi
	
}


function new_access_token
{
	echo -en > "$access_token_filepath";
	authString=`initAuth`;
	authResponseCode=`getResponseCode "$authString"`;
	authDataString=`getHTTPBody "$authString"`;

#echo `getKeyedValue '{"error":"invalid_client","error_description":"Invalid client id and client secret combination."}' 'error_description'`;

	if [ "$authResponseCode" -ne 200 ];
	then 
		# errString=`getKeyedValue "$authDataString" '^\["error_description"\]'`;
		errString=`echo "$authDataString" | jq '. .error_description'`;
		echo "$errString"
# 		echo '<?xml version="1.0" encoding="UTF-8" ?>';
# 		echo '<error>'`echo "$errString" | tr '[[:punct:]]' ' ' `'</error>';
		exit 1;
	fi;
	# access_token=`getKeyedValue "$authDataString" '^\["access_token"\]'`;
	access_token=`echo "$authDataString" | jq '. .access_token ' | tr -d '"'`;
	# refresh_token=`getKeyedValue "$authDataString" '^\["refresh_token"\]'`;
	refresh_token=`echo "$authDataString" | jq '. .refresh_token'`;
	echo "$access_token" > "$access_token_filepath"; # store it for persistent re-use
}

function get_media_data
{
	media_getString=`curl -s -S -XGET -i "https://api.cimediacloud.com/assets/$media_item_id/download" \
    -H "Authorization: Bearer $access_token"`
	media_getResponseCode=`getResponseCode "$media_getString"`;
	mediaDataString=`getHTTPBody "$media_getString"`;
}

# make sure your version of curl handles https
if [ -z "$(curl --version | tr '[[:space:]]' '\n' | grep https)" ]
then
	echo "cannot use this version of curl; it must handle https"
	exit 1;
fi;


if [ -z "$access_token" ];
then 
	new_access_token;
fi;


# NOW GO GET THAT MEDIA ITEM
get_media_data;

if [ "$media_getResponseCode" -ne 200 ];
then
	new_access_token;
	get_media_data;
fi;

if [ "$media_getResponseCode" -ne 200 ];
then 
	#errString=`getKeyedValue "$mediaDataString" '^\["error_description"\]'`;
	errString=`echo "$mediaDataString" | jq '. .error_description'`;
	echo "$errString"
# 	echo '<?xml version="1.0" encoding="UTF-8" ?>';
# 	echo '<error>'`echo "$errString" | tr '[[:punct:]]' ' ' `'</error>';
	exit 1;
fi;

#media_URL=$(getKeyedValue "$mediaDataString" '^\["location"\]' ); #| sed -e 's#&#&amp;#g'`;
media_URL=$(echo "$mediaDataString" | jq '. .location' );

echo $media_URL
exit;

## XML ops not necessary anymore




media_size=$(echo "$mediaDataString" | jq '. .size' );

# echo "$mediaDataString" > /tmp/"$1".json ;

# DISCARD LOCATIONS OF PROXIES AND GET THE PRIMARY LOCATION VALUE
#media_URL=$(echo "$media_getString" | grep '{' | tr '{][}' '\n' | grep '"location":' | grep -v 'BitRate' | sed -e 's#"location":#&\
#g' | grep -A1 '"location":' | tail -1 | cut -f2 -d\" | sed -e 's#&#&amp;#g');



#echo "media url is $media_URL";
#media url is https://ci-buckets-assets-1umcaf2mqwhhg.s3.amazonaws.com/cifiles/4bcdbbae70f14a5c822be7380e2ca26a/cpb-aacip-15-000000002m__barcode48704_.h264.mp4?AWSAccessKeyId=AKIAIIRADF3LJIY2O5IA&Expires=1428158705&response-content-disposition=attachment%3B%20filename%3Dcpb-aacip-15-000000002m__barcode48704_.h264.mp4&response-content-type=application%2Foctet-stream&Signature=zsJeRWOvrgUG1b2XhXrtIiZF5vU%3D&u=ae06218b8980440e9eb7c737e90dcf6b&a=4bcdbbae70f14a5c822be7380e2ca26a&ct=42cff4f6dbd74474808dee3c9ab49092

media_format=`echo "$media_URL" | tr '?' '\n' | head -1 | tr '.' '\n' | tail -1`;

#echo "media_format is $media_format"
#media_format is mp4

echo '<?xml version="1.0" encoding="UTF-8" ?>';
echo "<data>";
echo "   <format>$media_format</format>";
echo '   <mediaurl>'`echo "$media_URL" | sed -e 's#&#&amp;#g'`'</mediaurl>';
echo '   <size>'`echo "$media_size"`'</size>';
echo "</data>"; 
exit;







# 
# exit # COMMENT/REMOVE ANYTHING FOLLOWING AFTER TESTING
echo config_file_path is "$config_file_path"
echo credString is "$credString"
echo client_id is "$client_id"
echo client_secret is "$client_secret"
echo workspace_id is "$workspace_id"
echo access_token_filepath is "$access_token_filepath"
echo access_token is "$access_token"
echo
sampleAuthString=$(initAuth);
echo 'if authString is '
echo "$sampleAuthString"
echo
echo 'then refresh_token is '
echo $(getKeyedValue "$sampleAuthString" '^\["refresh_token"\]')
echo 
echo media_getString is "$media_getString"
echo media_getResponseCode is "$media_getResponseCode"
echo media_URL is "$media_URL"
echo media_format is "$media_format"




# echo "$authString";
# 
# HTTP/1.1 200 OK
# 
# Cache-Control: no-cache
# 
# Content-Type: application/json; charset=utf-8
# 
# Date: Fri, 03 Apr 2015 19:29:22 GMT
# 
# Expires: -1
# 
# Pragma: no-cache
# 
# X-Frame-Options: deny
# 
# Content-Length: 143
# 
# Connection: keep-alive
# 
# 
# 
# {"access_token":"1d802e8f2146481983c07f9959b8f101","expires_in":86400,"token_type":"bearer","refresh_token":"59a2ffc7ff19403ba170bdbb1ec7c928"}

#echo "$authString";
#echo "$authResponseCode";










