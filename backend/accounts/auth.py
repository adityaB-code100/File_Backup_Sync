from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from accounts.models import User
from bson import ObjectId
import mongoengine as me

class MongoJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        try:
            user_id = validated_token.get('user_id')
            if not user_id:
                raise InvalidToken('Token contained no user identifier')
            
            user = User.objects.get(id=ObjectId(user_id))
            return user
        except me.DoesNotExist:
            raise AuthenticationFailed('User not found', code='user_not_found')
        except Exception as e:
            raise InvalidToken(f'Invalid user token: {str(e)}')

def get_tokens_for_user(user):
    refresh = RefreshToken()
    refresh['user_id'] = str(user.id)
    refresh['email'] = user.email
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }
